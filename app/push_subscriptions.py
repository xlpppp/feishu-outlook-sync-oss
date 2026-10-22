"""Create / renew / cleanup Feishu + Graph push subscriptions per user."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import feishu_api, graph_api, tokens
from .config import get_settings
from .models import (
    DIR_BIDIRECTIONAL,
    DIR_FEISHU_TO_OUTLOOK,
    DIR_OUTLOOK_TO_FEISHU,
    PUSH_PROVIDER_FEISHU,
    PUSH_PROVIDER_MS,
    PushSubscription,
    User,
)

log = logging.getLogger("push_subscriptions")

# Graph resource for personal mailbox events (calendar-scoped path not supported
# for Outlook events in Graph v1.0 — sync_user anti-loop still avoids ping-pong).
GRAPH_EVENTS_RESOURCE = "/me/events"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _direction(user: User) -> str:
    d = (user.sync_direction or DIR_FEISHU_TO_OUTLOOK).strip()
    if d not in (
        DIR_FEISHU_TO_OUTLOOK,
        DIR_OUTLOOK_TO_FEISHU,
        DIR_BIDIRECTIONAL,
    ):
        return DIR_FEISHU_TO_OUTLOOK
    return d


def needs_feishu_push(user: User) -> bool:
    """Feishu calendar event push only when Feishu is a sync source."""
    return _direction(user) in (DIR_FEISHU_TO_OUTLOOK, DIR_BIDIRECTIONAL)


def needs_graph_push(user: User) -> bool:
    """Graph event push only when Outlook is a sync source."""
    return _direction(user) in (DIR_OUTLOOK_TO_FEISHU, DIR_BIDIRECTIONAL)


def _upsert_row(
    db: Session,
    user_id: int,
    provider: str,
    resource: str,
    *,
    subscription_id: Optional[str],
    expires_at: Optional[datetime],
    client_state: Optional[str],
    raw_meta: Optional[dict],
) -> PushSubscription:
    row = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user_id,
            PushSubscription.provider == provider,
            PushSubscription.resource == resource,
        )
        .one_or_none()
    )
    if row is None:
        row = PushSubscription(
            user_id=user_id, provider=provider, resource=resource
        )
        db.add(row)
    row.subscription_id = subscription_id
    row.expires_at = expires_at
    row.client_state = client_state
    row.raw_meta = json.dumps(raw_meta, ensure_ascii=False) if raw_meta else None
    row.updated_at = _utcnow()
    db.flush()
    return row


def ensure_user_subscriptions(db: Session, user: User) -> None:
    """
    Create/refresh push subscriptions when sync is enabled and push is configured.
    Safe to call after OAuth connect, direction change, or sync toggle on.
    """
    settings = get_settings()
    if not settings.push_sync_enabled:
        return
    if not user.sync_enabled:
        cleanup_user_subscriptions(db, user)
        return

    if settings.feishu_push_active() and needs_feishu_push(user):
        try:
            _ensure_feishu(db, user)
        except Exception:
            log.exception("确保飞书推送订阅失败 user=%s", user.id)
    else:
        _cleanup_provider(db, user, PUSH_PROVIDER_FEISHU)

    if settings.graph_push_active() and needs_graph_push(user):
        try:
            _ensure_graph(db, user)
        except Exception:
            log.exception("确保 Graph 推送订阅失败 user=%s", user.id)
    else:
        _cleanup_provider(db, user, PUSH_PROVIDER_MS)


def cleanup_user_subscriptions(
    db: Session,
    user: User,
    *,
    provider: Optional[str] = None,
) -> None:
    """Remove remote + local subscriptions (disconnect / disable)."""
    if provider:
        _cleanup_provider(db, user, provider)
        return
    _cleanup_provider(db, user, PUSH_PROVIDER_FEISHU)
    _cleanup_provider(db, user, PUSH_PROVIDER_MS)


def _cleanup_provider(db: Session, user: User, provider: str) -> None:
    rows = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user.id,
            PushSubscription.provider == provider,
        )
        .all()
    )
    if not rows:
        return

    if provider == PUSH_PROVIDER_FEISHU and tokens.has_token(
        db, user.id, tokens.PROVIDER_FEISHU
    ):
        try:
            ftoken = tokens.get_valid_access_token(
                db, user, tokens.PROVIDER_FEISHU
            )
            for row in rows:
                try:
                    feishu_api.unsubscribe_calendar_events(ftoken, row.resource)
                except Exception as e:
                    log.warning(
                        "取消飞书订阅失败 user=%s resource=%s: %s",
                        user.id,
                        row.resource[:32],
                        e,
                    )
        except Exception as e:
            log.warning("取消飞书订阅时取 token 失败 user=%s: %s", user.id, e)

    if provider == PUSH_PROVIDER_MS and tokens.has_token(
        db, user.id, tokens.PROVIDER_MS
    ):
        try:
            mtoken = tokens.get_valid_access_token(db, user, tokens.PROVIDER_MS)
            for row in rows:
                if not row.subscription_id:
                    continue
                try:
                    graph_api.delete_subscription(mtoken, row.subscription_id)
                except Exception as e:
                    log.warning(
                        "删除 Graph 订阅失败 user=%s: %s", user.id, e
                    )
        except Exception as e:
            log.warning("删除 Graph 订阅时取 token 失败 user=%s: %s", user.id, e)

    for row in rows:
        db.delete(row)
    db.flush()


def _ensure_feishu(db: Session, user: User) -> None:
    if not tokens.has_token(db, user.id, tokens.PROVIDER_FEISHU):
        return
    settings = get_settings()
    ftoken = tokens.get_valid_access_token(db, user, tokens.PROVIDER_FEISHU)
    calendars = feishu_api.list_calendars(ftoken)
    targets = feishu_api.calendars_for_event_subscription(
        calendars,
        exclude_calendar_name=settings.feishu_sync_calendar_name,
        skip_subscribed=settings.skip_subscribed_calendars,
    )
    wanted = {
        str(c.get("calendar_id") or c.get("id"))
        for c in targets
        if (c.get("calendar_id") or c.get("id"))
    }
    existing = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user.id,
            PushSubscription.provider == PUSH_PROVIDER_FEISHU,
        )
        .all()
    )
    for row in existing:
        if row.resource not in wanted:
            try:
                feishu_api.unsubscribe_calendar_events(ftoken, row.resource)
            except Exception as e:
                log.warning("清理多余飞书订阅失败: %s", e)
            db.delete(row)

    for cid in wanted:
        try:
            feishu_api.subscribe_calendar_events(ftoken, cid)
        except Exception as e:
            # Already subscribed is often still code=0; log and keep row
            log.warning("飞书 subscribe 失败 calendar=%s…: %s", cid[:24], e)
            continue
        _upsert_row(
            db,
            user.id,
            PUSH_PROVIDER_FEISHU,
            cid,
            subscription_id=cid,
            expires_at=None,  # Feishu calendar event subscription does not expire like Graph
            client_state=None,
            raw_meta={"kind": "feishu_calendar_events"},
        )
    db.flush()
    log.info("飞书推送订阅已就绪 user=%s calendars=%d", user.id, len(wanted))


def _ensure_graph(db: Session, user: User) -> None:
    if not tokens.has_token(db, user.id, tokens.PROVIDER_MS):
        return
    settings = get_settings()
    if not settings.graph_webhook_client_state:
        return
    mtoken = tokens.get_valid_access_token(db, user, tokens.PROVIDER_MS)
    resource = GRAPH_EVENTS_RESOURCE
    row = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.user_id == user.id,
            PushSubscription.provider == PUSH_PROVIDER_MS,
            PushSubscription.resource == resource,
        )
        .one_or_none()
    )

    # Renew if still valid and far from expiry
    renew_before = _utcnow() + timedelta(
        hours=max(1, settings.graph_subscription_renew_hours)
    )
    if (
        row
        and row.subscription_id
        and row.expires_at
        and row.expires_at > renew_before
    ):
        return

    if row and row.subscription_id:
        try:
            data = graph_api.renew_subscription(mtoken, row.subscription_id)
            exp = _parse_graph_expiry(data.get("expirationDateTime"))
            _upsert_row(
                db,
                user.id,
                PUSH_PROVIDER_MS,
                resource,
                subscription_id=row.subscription_id,
                expires_at=exp,
                client_state=settings.graph_webhook_client_state,
                raw_meta={"kind": "graph_events", "renewed": True},
            )
            return
        except Exception as e:
            log.warning(
                "Graph 续期失败，将重建 user=%s: %s", user.id, e
            )
            try:
                graph_api.delete_subscription(mtoken, row.subscription_id)
            except Exception:
                pass

    notify_url = settings.microsoft_webhook_url
    data = graph_api.create_subscription(
        mtoken,
        resource=resource,
        notification_url=notify_url,
        client_state=settings.graph_webhook_client_state,
        lifecycle_notification_url=notify_url,
    )
    exp = _parse_graph_expiry(data.get("expirationDateTime"))
    _upsert_row(
        db,
        user.id,
        PUSH_PROVIDER_MS,
        resource,
        subscription_id=str(data["id"]),
        expires_at=exp,
        client_state=settings.graph_webhook_client_state,
        raw_meta={"kind": "graph_events", "resource": resource},
    )
    log.info("Graph 推送订阅已就绪 user=%s", user.id)


def _parse_graph_expiry(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # Graph returns e.g. 2026-10-27T12:00:00.0000000Z
        cleaned = raw.replace("Z", "+00:00")
        if "." in cleaned:
            # trim fractional to 6 digits for fromisoformat
            head, rest = cleaned.split(".", 1)
            frac = ""
            tz = "+00:00"
            for i, ch in enumerate(rest):
                if ch.isdigit():
                    frac += ch
                else:
                    tz = rest[i:]
                    break
            frac = (frac + "000000")[:6]
            cleaned = f"{head}.{frac}{tz}"
        return datetime.fromisoformat(cleaned)
    except Exception:
        log.warning("无法解析 Graph expirationDateTime: %s", raw)
        return _utcnow() + timedelta(days=6)


def renew_expiring_graph_subscriptions(db: Session) -> int:
    """Background: renew MS subscriptions nearing expiry. Returns count renewed."""
    settings = get_settings()
    if not settings.graph_push_active():
        return 0
    threshold = _utcnow() + timedelta(
        hours=max(1, settings.graph_subscription_renew_hours)
    )
    rows = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.provider == PUSH_PROVIDER_MS,
            PushSubscription.expires_at.isnot(None),
            PushSubscription.expires_at <= threshold,
        )
        .all()
    )
    n = 0
    for row in rows:
        user = db.get(User, row.user_id)
        if not user or not user.sync_enabled or not needs_graph_push(user):
            continue
        try:
            _ensure_graph(db, user)
            n += 1
        except Exception:
            log.exception("续期 Graph 订阅失败 user=%s", row.user_id)
    return n


def handle_graph_lifecycle(
    db: Session,
    *,
    subscription_id: str,
    lifecycle_event: str,
) -> None:
    """
    Handle missed / reauthorizationRequired / subscriptionRemoved.
    """
    row = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.provider == PUSH_PROVIDER_MS,
            PushSubscription.subscription_id == subscription_id,
        )
        .one_or_none()
    )
    if row is None:
        log.warning(
            "Graph lifecycle 未知订阅 id=%s… event=%s",
            subscription_id[:12],
            lifecycle_event,
        )
        return
    user = db.get(User, row.user_id)
    if user is None:
        return
    log.info(
        "Graph lifecycle user=%s event=%s id=%s…",
        user.id,
        lifecycle_event,
        subscription_id[:12],
    )
    if lifecycle_event == "reauthorizationRequired":
        if tokens.has_token(db, user.id, tokens.PROVIDER_MS):
            try:
                mtoken = tokens.get_valid_access_token(
                    db, user, tokens.PROVIDER_MS
                )
                graph_api.reauthorize_subscription(mtoken, subscription_id)
            except Exception:
                log.exception("reauthorize 失败 user=%s，尝试重建", user.id)
                _ensure_graph(db, user)
        return
    if lifecycle_event in ("subscriptionRemoved", "missed"):
        # Recreate + trigger a catch-up sync via caller enqueue
        try:
            _ensure_graph(db, user)
        except Exception:
            log.exception("lifecycle 重建订阅失败 user=%s", user.id)


def find_user_ids_for_feishu_event(
    db: Session,
    *,
    calendar_id: Optional[str],
    open_ids: list[str],
) -> list[int]:
    """Map Feishu webhook payload to local user ids."""
    ids: set[int] = set()
    if open_ids:
        users = (
            db.query(User)
            .filter(User.feishu_open_id.in_(open_ids))
            .all()
        )
        for u in users:
            ids.add(u.id)
    if calendar_id:
        rows = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.provider == PUSH_PROVIDER_FEISHU,
                PushSubscription.resource == calendar_id,
            )
            .all()
        )
        for r in rows:
            ids.add(r.user_id)
    return sorted(ids)


def find_user_id_for_graph_subscription(
    db: Session, subscription_id: str
) -> Optional[int]:
    row = (
        db.query(PushSubscription)
        .filter(
            PushSubscription.provider == PUSH_PROVIDER_MS,
            PushSubscription.subscription_id == subscription_id,
        )
        .one_or_none()
    )
    return row.user_id if row else None
