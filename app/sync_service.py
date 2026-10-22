"""Per-user calendar sync engine (Feishu ↔ Outlook)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import feishu_api, graph_api, tokens
from .config import get_settings
from .models import (
    DIR_BIDIRECTIONAL,
    DIR_FEISHU_TO_OUTLOOK,
    DIR_OUTLOOK_TO_FEISHU,
    ORIGIN_F2O,
    ORIGIN_O2F,
    EventMapping,
    User,
)
from .util import (
    event_content_hash,
    feishu_event_to_graph_payload,
    graph_event_to_feishu_payload,
    outlook_event_content_hash,
    sync_window,
)

log = logging.getLogger("sync_service")


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: int = 0
    message: str = ""
    dry_run: bool = False
    direction: str = ""

    def summary(self) -> str:
        dir_part = f"[{self.direction}] " if self.direction else ""
        return (
            f"{dir_part}create={self.created} update={self.updated} "
            f"skip={self.skipped} delete={self.deleted} errors={self.errors}"
            + (" [dry-run]" if self.dry_run else "")
        )

    def merge(self, other: "SyncResult") -> None:
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.deleted += other.deleted
        self.errors += other.errors


def sync_user(
    db: Session,
    user: User,
    *,
    dry_run: bool = False,
    trigger: str = "manual",
) -> SyncResult:
    # trigger: poll|push|manual|admin — threaded from scheduler/push/dashboard call sites
    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    direction = (user.sync_direction or DIR_FEISHU_TO_OUTLOOK).strip()
    if direction not in (
        DIR_FEISHU_TO_OUTLOOK,
        DIR_OUTLOOK_TO_FEISHU,
        DIR_BIDIRECTIONAL,
    ):
        direction = DIR_FEISHU_TO_OUTLOOK

    result = SyncResult(dry_run=dry_run, direction=direction)

    if not tokens.has_token(db, user.id, tokens.PROVIDER_FEISHU):
        result.errors = 1
        result.message = "未连接飞书"
        _record(
            db,
            user,
            "error",
            result.message,
            trigger=trigger,
            result=result,
            started_at=started_at,
            dry_run=dry_run,
        )
        return result
    if not tokens.has_token(db, user.id, tokens.PROVIDER_MS):
        result.errors = 1
        result.message = "未连接 Outlook"
        _record(
            db,
            user,
            "error",
            result.message,
            trigger=trigger,
            result=result,
            started_at=started_at,
            dry_run=dry_run,
        )
        return result

    try:
        feishu_token = tokens.get_valid_access_token(
            db, user, tokens.PROVIDER_FEISHU
        )
        ms_token = tokens.get_valid_access_token(db, user, tokens.PROVIDER_MS)
    except Exception as e:
        result.errors = 1
        result.message = f"获取令牌失败: {e}"
        _record(
            db,
            user,
            "error",
            result.message,
            trigger=trigger,
            result=result,
            started_at=started_at,
            dry_run=dry_run,
        )
        return result

    start, end = sync_window(
        settings.sync_window_past_days,
        settings.sync_window_future_days,
        settings.timezone,
    )

    messages: list[str] = []

    if direction in (DIR_FEISHU_TO_OUTLOOK, DIR_BIDIRECTIONAL):
        leg = _sync_feishu_to_outlook(
            db,
            user,
            feishu_token=feishu_token,
            ms_token=ms_token,
            start=start,
            end=end,
            dry_run=dry_run,
        )
        result.merge(leg)
        messages.append(leg.summary())

    if direction in (DIR_OUTLOOK_TO_FEISHU, DIR_BIDIRECTIONAL):
        leg = _sync_outlook_to_feishu(
            db,
            user,
            feishu_token=feishu_token,
            ms_token=ms_token,
            start=start,
            end=end,
            dry_run=dry_run,
        )
        result.merge(leg)
        messages.append(leg.summary())

    result.direction = direction
    result.message = " | ".join(messages) if messages else result.summary()
    if not result.message:
        result.message = result.summary()
    touched = result.created + result.updated + result.deleted + result.skipped
    if result.errors == 0:
        status = "ok"
    elif touched == 0:
        status = "error"
    else:
        status = "partial"
    _record(
        db,
        user,
        status,
        result.message,
        trigger=trigger,
        result=result,
        started_at=started_at,
        dry_run=dry_run,
    )
    if not dry_run:
        db.commit()
    return result


def _sync_feishu_to_outlook(
    db: Session,
    user: User,
    *,
    feishu_token: str,
    ms_token: str,
    start: datetime,
    end: datetime,
    dry_run: bool,
) -> SyncResult:
    """Feishu primary → Outlook calendar named OUTLOOK_CALENDAR_NAME."""
    settings = get_settings()
    result = SyncResult(dry_run=dry_run, direction=ORIGIN_F2O)
    exclude_name = settings.feishu_sync_calendar_name

    try:
        events = feishu_api.pull_primary_events(
            feishu_token,
            start=start,
            end=end,
            exclude_calendar_name=exclude_name,
            skip_subscribed=settings.skip_subscribed_calendars,
        )
    except Exception as e:
        result.errors = 1
        result.message = f"拉取飞书失败: {e}"
        log.exception("user=%s 拉取飞书失败", user.id)
        return result

    log.info("user=%s [f2o] 飞书事件 %d", user.id, len(events))
    current_ids = {str(e["event_id"]) for e in events if e.get("event_id")}

    mappings = {
        m.feishu_event_id: m
        for m in db.query(EventMapping)
        .filter(
            EventMapping.user_id == user.id,
            EventMapping.direction == ORIGIN_F2O,
        )
        .all()
    }

    cal_name = user.outlook_calendar_name or settings.outlook_calendar_name
    try:
        cal = graph_api.ensure_calendar(cal_name, ms_token)
        cal_id = cal["id"]
        user.outlook_calendar_id = cal_id
        user.outlook_calendar_name = cal_name
        db.flush()
    except Exception as e:
        result.errors = 1
        result.message = f"确保 Outlook 日历失败: {e}"
        return result

    # Once per sync: IDs present in target calendarView for this window.
    # Hash-equal mappings whose outlook_event_id is absent are orphans → recreate.
    try:
        target_events = graph_api.list_events(ms_token, cal_id, start, end)
        present_outlook_ids = {str(e["id"]) for e in target_events if e.get("id")}
    except Exception as e:
        result.errors = 1
        result.message = f"拉取 Outlook 目标日历失败: {e}"
        log.exception("user=%s [f2o] 拉取目标日历失败", user.id)
        return result

    if dry_run:
        for ev in events:
            eid = str(ev["event_id"])
            h = event_content_hash(ev, settings.timezone)
            mapped = mappings.get(eid)
            if mapped is None:
                result.created += 1
            elif mapped.outlook_event_id not in present_outlook_ids:
                result.created += 1
            elif mapped.content_hash == h:
                result.skipped += 1
            else:
                result.updated += 1
        for eid in mappings:
            if eid not in current_ids:
                result.deleted += 1
        result.message = result.summary()
        return result

    for ev in events:
        eid = str(ev["event_id"])
        summary = ev.get("summary") or "(无标题)"
        h = event_content_hash(ev, settings.timezone)
        try:
            payload = feishu_event_to_graph_payload(
                ev, default_tz=settings.timezone
            )
        except Exception as e:
            log.error("构造 payload 失败 %s: %s", eid, e)
            result.errors += 1
            continue

        mapped = mappings.get(eid)
        try:
            if mapped is None:
                created_ev = graph_api.create_event(cal_id, payload, ms_token)
                oid = str(created_ev["id"])
                row = EventMapping(
                    user_id=user.id,
                    feishu_event_id=eid,
                    outlook_event_id=oid,
                    content_hash=h,
                    direction=ORIGIN_F2O,
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(row)
                mappings[eid] = row
                present_outlook_ids.add(oid)
                result.created += 1
                log.info("CREATE[f2o] user=%s %s", user.id, summary)
            elif mapped.outlook_event_id not in present_outlook_ids:
                # Mapping stale / Outlook event deleted — recreate, keep row.
                created_ev = graph_api.create_event(cal_id, payload, ms_token)
                oid = str(created_ev["id"])
                mapped.outlook_event_id = oid
                mapped.content_hash = h
                mapped.updated_at = datetime.now(timezone.utc)
                present_outlook_ids.add(oid)
                result.created += 1
                log.info(
                    "RECREATE[f2o] user=%s %s (目标缺失 outlook_id)",
                    user.id,
                    summary,
                )
            elif mapped.content_hash == h:
                result.skipped += 1
            else:
                graph_api.update_event(
                    mapped.outlook_event_id, payload, ms_token
                )
                mapped.content_hash = h
                mapped.updated_at = datetime.now(timezone.utc)
                result.updated += 1
                log.info("UPDATE[f2o] user=%s %s", user.id, summary)
        except Exception as e:
            log.error("写入失败[f2o] user=%s %s: %s", user.id, summary, e)
            result.errors += 1

    for eid in list(mappings.keys()):
        if eid in current_ids:
            continue
        mapped = mappings[eid]
        try:
            graph_api.delete_event(mapped.outlook_event_id, ms_token)
            db.delete(mapped)
            result.deleted += 1
            log.info("DELETE[f2o] user=%s feishu=%s", user.id, eid)
        except graph_api.GraphApiError as e:
            msg = str(e)
            if "404" in msg or "ErrorItemNotFound" in msg:
                db.delete(mapped)
                result.deleted += 1
            else:
                log.error("删除失败[f2o] %s: %s", eid, e)
                result.errors += 1
        except Exception as e:
            log.error("删除失败[f2o] %s: %s", eid, e)
            result.errors += 1

    result.message = result.summary()
    db.flush()
    return result


def _sync_outlook_to_feishu(
    db: Session,
    user: User,
    *,
    feishu_token: str,
    ms_token: str,
    start: datetime,
    end: datetime,
    dry_run: bool,
) -> SyncResult:
    """
    Outlook primary → Feishu calendar named FEISHU_SYNC_CALENDAR_NAME.
    Anti-loop: never read from Outlook calendar OUTLOOK_CALENDAR_NAME.
    """
    settings = get_settings()
    result = SyncResult(dry_run=dry_run, direction=ORIGIN_O2F)
    outlook_target_name = (
        user.outlook_calendar_name or settings.outlook_calendar_name
    )
    feishu_target_name = settings.feishu_sync_calendar_name

    try:
        default_cal = graph_api.get_default_calendar(ms_token)
        src_cal_id = default_cal["id"]
        src_name = (default_cal.get("name") or "").strip()
        if src_name == outlook_target_name.strip():
            result.errors = 1
            result.message = (
                f"Outlook 默认日历名称与同步目标「{outlook_target_name}」相同，"
                "请重命名其一以避免回环"
            )
            return result
        events = graph_api.list_events(ms_token, src_cal_id, start, end)
    except Exception as e:
        result.errors = 1
        result.message = f"拉取 Outlook 失败: {e}"
        log.exception("user=%s 拉取 Outlook 失败", user.id)
        return result

    log.info("user=%s [o2f] Outlook 事件 %d", user.id, len(events))
    current_ids = {str(e["id"]) for e in events if e.get("id")}

    mappings = {
        m.outlook_event_id: m
        for m in db.query(EventMapping)
        .filter(
            EventMapping.user_id == user.id,
            EventMapping.direction == ORIGIN_O2F,
        )
        .all()
    }

    try:
        fcal = feishu_api.ensure_named_calendar(feishu_token, feishu_target_name)
        fcal_id = fcal.get("calendar_id") or fcal.get("id")
        if not fcal_id:
            raise feishu_api.FeishuApiError("飞书目标日历缺少 calendar_id")
    except Exception as e:
        result.errors = 1
        result.message = f"确保飞书日历失败: {e}"
        return result

    # Once per sync: IDs present on Feishu target calendar in this window.
    try:
        target_events = feishu_api.list_events(
            feishu_token, fcal_id, start=start, end=end
        )
        present_feishu_ids = {
            str(e["event_id"]) for e in target_events if e.get("event_id")
        }
    except Exception as e:
        result.errors = 1
        result.message = f"拉取飞书目标日历失败: {e}"
        log.exception("user=%s [o2f] 拉取目标日历失败", user.id)
        return result

    if dry_run:
        for ev in events:
            oid = str(ev["id"])
            h = outlook_event_content_hash(ev, settings.timezone)
            mapped = mappings.get(oid)
            if mapped is None:
                result.created += 1
            elif mapped.feishu_event_id not in present_feishu_ids:
                result.created += 1
            elif mapped.content_hash == h:
                result.skipped += 1
            else:
                result.updated += 1
        for oid in mappings:
            if oid not in current_ids:
                result.deleted += 1
        result.message = result.summary()
        return result

    for ev in events:
        oid = str(ev["id"])
        summary = ev.get("subject") or "(无标题)"
        h = outlook_event_content_hash(ev, settings.timezone)
        try:
            payload = graph_event_to_feishu_payload(
                ev, default_tz=settings.timezone
            )
        except Exception as e:
            log.error("构造 Feishu payload 失败 %s: %s", oid, e)
            result.errors += 1
            continue

        mapped = mappings.get(oid)
        try:
            if mapped is None:
                created_ev = feishu_api.create_event(
                    feishu_token, fcal_id, payload
                )
                fid = str(created_ev["event_id"])
                row = EventMapping(
                    user_id=user.id,
                    feishu_event_id=fid,
                    outlook_event_id=oid,
                    content_hash=h,
                    direction=ORIGIN_O2F,
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(row)
                mappings[oid] = row
                present_feishu_ids.add(fid)
                result.created += 1
                log.info("CREATE[o2f] user=%s %s", user.id, summary)
            elif mapped.feishu_event_id not in present_feishu_ids:
                created_ev = feishu_api.create_event(
                    feishu_token, fcal_id, payload
                )
                fid = str(created_ev["event_id"])
                mapped.feishu_event_id = fid
                mapped.content_hash = h
                mapped.updated_at = datetime.now(timezone.utc)
                present_feishu_ids.add(fid)
                result.created += 1
                log.info(
                    "RECREATE[o2f] user=%s %s (目标缺失 feishu_id)",
                    user.id,
                    summary,
                )
            elif mapped.content_hash == h:
                result.skipped += 1
            else:
                feishu_api.patch_event(
                    feishu_token,
                    fcal_id,
                    mapped.feishu_event_id,
                    payload,
                )
                mapped.content_hash = h
                mapped.updated_at = datetime.now(timezone.utc)
                result.updated += 1
                log.info("UPDATE[o2f] user=%s %s", user.id, summary)
        except Exception as e:
            log.error("写入失败[o2f] user=%s %s: %s", user.id, summary, e)
            result.errors += 1

    for oid in list(mappings.keys()):
        if oid in current_ids:
            continue
        mapped = mappings[oid]
        try:
            feishu_api.delete_event(
                feishu_token, fcal_id, mapped.feishu_event_id
            )
            db.delete(mapped)
            result.deleted += 1
            log.info("DELETE[o2f] user=%s outlook=%s", user.id, oid)
        except feishu_api.FeishuApiError as e:
            msg = str(e)
            if "404" in msg or "193001" in msg or "not found" in msg.lower():
                db.delete(mapped)
                result.deleted += 1
            else:
                log.error("删除失败[o2f] %s: %s", oid, e)
                result.errors += 1
        except Exception as e:
            log.error("删除失败[o2f] %s: %s", oid, e)
            result.errors += 1

    result.message = result.summary()
    db.flush()
    return result


def _record(
    db: Session,
    user: User,
    status: str,
    message: str,
    *,
    trigger: str = "manual",
    result: SyncResult | None = None,
    started_at: datetime | None = None,
    dry_run: bool = False,
) -> None:
    finished = datetime.now(timezone.utc)
    user.last_sync_at = finished
    user.last_sync_status = status
    user.last_sync_message = (message or "")[:2000]
    db.flush()
    if dry_run:
        return
    # Skip SyncRun insert on dry_run; always keep users.last_sync_* above.
    from .sync_runs import record_sync_run

    msg = message or ""
    if result is not None and result.summary():
        # Prefer summary + optional longer message, truncated like last_sync_message
        summary = result.summary()
        if result.message and result.message != summary:
            msg = f"{summary} | {result.message}"
        else:
            msg = summary or msg
    record_sync_run(
        db,
        user.id,
        trigger=trigger,
        status=status if status in ("ok", "error", "partial") else "error",
        message=msg,
        created=result.created if result else 0,
        updated=result.updated if result else 0,
        deleted=result.deleted if result else 0,
        started_at=started_at or finished,
        finished_at=finished,
    )


def sync_all_enabled(db: Session, *, trigger: str = "poll") -> int:
    """Sync all users with sync_enabled and both tokens. Returns count attempted."""
    users = db.query(User).filter(User.sync_enabled.is_(True)).all()
    count = 0
    for user in users:
        if not tokens.has_token(db, user.id, tokens.PROVIDER_FEISHU):
            continue
        if not tokens.has_token(db, user.id, tokens.PROVIDER_MS):
            continue
        count += 1
        try:
            sync_user(db, user, dry_run=False, trigger=trigger)
        except Exception:
            log.exception("定时同步失败 user=%s", user.id)
    return count
