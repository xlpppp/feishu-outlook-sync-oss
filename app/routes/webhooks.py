"""Public webhook endpoints (no session cookie). Verify tokens / clientState."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from .. import feishu_events, push_debounce, push_subscriptions
from ..config import get_settings
from ..db import get_db
from ..models import User

log = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/feishu")
async def feishu_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Feishu event subscription endpoint.
    Handles url_verification (challenge) and calendar.calendar.event.changed_v4.
    Auth: Encrypt Key signature and/or Verification Token — not session cookies.
    """
    settings = get_settings()
    if not settings.feishu_push_active():
        return JSONResponse({"code": 1, "msg": "feishu push disabled"}, status_code=503)

    raw = await request.body()
    timestamp = request.headers.get("X-Lark-Request-Timestamp") or request.headers.get(
        "X-Lark-Request-Timestamp".lower(), ""
    )
    nonce = request.headers.get("X-Lark-Request-Nonce") or ""
    signature = request.headers.get("X-Lark-Signature") or ""

    try:
        payload = feishu_events.parse_event_payload(
            raw,
            encrypt_key=settings.feishu_event_encrypt_key,
            verification_token=settings.feishu_event_verification_token,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        )
    except feishu_events.FeishuEventError as e:
        log.warning("飞书 webhook 校验失败: %s", e)
        return JSONResponse({"code": 1, "msg": "invalid"}, status_code=401)

    if feishu_events.is_url_verification(payload):
        try:
            return JSONResponse(feishu_events.challenge_response(payload))
        except feishu_events.FeishuEventError as e:
            log.warning("飞书 challenge 失败: %s", e)
            return JSONResponse({"code": 1, "msg": "challenge error"}, status_code=400)

    change = feishu_events.extract_calendar_event_change(payload)
    if change is None:
        # Idempotent ack for unrelated subscribed events
        et = feishu_events.event_type(payload) or "unknown"
        log.info("飞书 webhook 忽略事件类型=%s", et)
        return JSONResponse({})

    user_ids = push_subscriptions.find_user_ids_for_feishu_event(
        db,
        calendar_id=change.get("calendar_id"),
        open_ids=change.get("open_ids") or [],
    )
    if not user_ids:
        log.info(
            "飞书事件无匹配用户 calendar=%s open_ids=%d",
            (change.get("calendar_id") or "")[:24],
            len(change.get("open_ids") or []),
        )
        return JSONResponse({})

    for uid in user_ids:
        user = db.get(User, uid)
        if not user or not user.sync_enabled:
            continue
        if not push_subscriptions.needs_feishu_push(user):
            continue
        log.info(
            "飞书推送触发入队 user=%s calendar=%s change=%s",
            uid,
            (change.get("calendar_id") or "")[:24],
            change.get("change_type") or "?",
        )
        push_debounce.schedule_user_sync(uid, reason="feishu_push")

    return JSONResponse({})


@router.post("/microsoft")
async def microsoft_webhook(
    request: Request,
    validationToken: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Microsoft Graph change + lifecycle notifications.
    validationToken handshake: echo plain text (no JSON).
    Auth: GRAPH_WEBHOOK_CLIENT_STATE compared to notification clientState.
    """
    settings = get_settings()

    # Subscription validation handshake (also used for lifecycle URL)
    if validationToken is not None:
        log.info("Graph webhook validationToken 握手")
        return PlainTextResponse(content=validationToken, status_code=200)

    if not settings.graph_push_active():
        return Response(status_code=503)

    try:
        body: Any = await request.json()
    except Exception:
        log.warning("Graph webhook 非 JSON 体")
        return Response(status_code=400)

    notifications = []
    if isinstance(body, dict):
        notifications = body.get("value") or []
    if not isinstance(notifications, list):
        return Response(status_code=202)

    expected_state = settings.graph_webhook_client_state
    for note in notifications:
        if not isinstance(note, dict):
            continue
        client_state = note.get("clientState")
        if expected_state and client_state != expected_state:
            log.warning("Graph webhook clientState 不匹配，已忽略")
            continue

        subscription_id = str(note.get("subscriptionId") or "")
        lifecycle = note.get("lifecycleEvent")
        if lifecycle:
            if subscription_id:
                try:
                    push_subscriptions.handle_graph_lifecycle(
                        db,
                        subscription_id=subscription_id,
                        lifecycle_event=str(lifecycle),
                    )
                    db.commit()
                except Exception:
                    log.exception("处理 Graph lifecycle 失败")
                    db.rollback()
                # Catch-up sync on missed / removed
                if str(lifecycle) in ("missed", "subscriptionRemoved"):
                    uid = push_subscriptions.find_user_id_for_graph_subscription(
                        db, subscription_id
                    )
                    if uid:
                        push_debounce.schedule_user_sync(
                            uid, reason=f"graph_lifecycle:{lifecycle}"
                        )
            continue

        if not subscription_id:
            continue
        uid = push_subscriptions.find_user_id_for_graph_subscription(
            db, subscription_id
        )
        if not uid:
            log.info("Graph 通知未知订阅 id=%s…", subscription_id[:12])
            continue
        user = db.get(User, uid)
        if not user or not user.sync_enabled:
            continue
        if not push_subscriptions.needs_graph_push(user):
            continue
        change_type = note.get("changeType") or "?"
        log.info(
            "Graph 推送触发入队 user=%s change=%s",
            uid,
            change_type,
        )
        push_debounce.schedule_user_sync(uid, reason="graph_push")

    # Acknowledge quickly; work is debounced
    return Response(status_code=202)
