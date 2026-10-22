"""Chinese HTML dashboard."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import push_subscriptions, tokens
from ..config import get_settings
from ..db import get_db
from ..models import (
    DIR_BIDIRECTIONAL,
    DIR_FEISHU_TO_OUTLOOK,
    DIR_OUTLOOK_TO_FEISHU,
    VALID_SYNC_DIRECTIONS,
    User,
)
from ..session_auth import get_session_user_id
from ..sync_service import sync_user

log = logging.getLogger("web")

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _dashboard_ctx(request: Request, db: Session, flash: str | None, flash_err: str | None):
    settings = get_settings()
    uid = get_session_user_id(request)
    user = db.get(User, uid) if uid else None
    sync_direction = (
        (user.sync_direction if user else None) or DIR_FEISHU_TO_OUTLOOK
    )
    outlook_target = (
        (user.outlook_calendar_name if user else None)
        or settings.outlook_calendar_name
    )
    feishu_target = settings.feishu_sync_calendar_name
    needs_write = settings.needs_feishu_write(sync_direction)
    is_admin = bool(user and settings.is_admin_open_id(user.feishu_open_id))

    return {
        "request": request,
        "user": user,
        "flash": flash,
        "flash_error": flash_err == "1",
        "is_admin": is_admin,
        "ms_connected": bool(
            user and tokens.has_token(db, user.id, tokens.PROVIDER_MS)
        ),
        "feishu_connected": bool(
            user and tokens.has_token(db, user.id, tokens.PROVIDER_FEISHU)
        ),
        "calendar_name": outlook_target,
        "outlook_target_calendar_name": outlook_target,
        "feishu_target_calendar_name": feishu_target,
        "sync_direction": sync_direction,
        "needs_feishu_write": needs_write,
        "dir_feishu_to_outlook": DIR_FEISHU_TO_OUTLOOK,
        "dir_outlook_to_feishu": DIR_OUTLOOK_TO_FEISHU,
        "dir_bidirectional": DIR_BIDIRECTIONAL,
        "sync_interval": settings.sync_interval_minutes,
        "public_base_url": settings.public_base_url,
    }


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    flash: str | None = None,
    flash_err: str | None = None,
    db: Session = Depends(get_db),
):
    ctx = _dashboard_ctx(request, db, flash, flash_err)
    return templates.TemplateResponse(request, "index.html", ctx)


@router.post("/sync/now")
def sync_now_form(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    if not uid:
        return RedirectResponse(
            "/?flash=请先连接账户&flash_err=1", status_code=302
        )
    user = db.get(User, uid)
    if not user:
        return RedirectResponse(
            "/?flash=会话无效&flash_err=1", status_code=302
        )
    result = sync_user(db, user, dry_run=False, trigger="manual")
    err = "1" if result.errors else "0"
    msg = quote(f"同步完成：{result.message}")
    return RedirectResponse(f"/?flash={msg}&flash_err={err}", status_code=302)


@router.post("/api/sync/toggle")
def toggle_sync(
    request: Request,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
):
    uid = get_session_user_id(request)
    if not uid:
        return RedirectResponse(
            "/?flash=未登录&flash_err=1", status_code=302
        )
    user = db.get(User, uid)
    if user:
        user.sync_enabled = enabled in ("1", "true", "on")
        try:
            if user.sync_enabled:
                push_subscriptions.ensure_user_subscriptions(db, user)
            else:
                push_subscriptions.cleanup_user_subscriptions(db, user)
        except Exception:
            log.exception("切换自动同步时更新推送订阅失败 user=%s", user.id)
        db.commit()
    return RedirectResponse("/?flash=已更新自动同步设置", status_code=302)


@router.post("/api/sync/direction")
@router.post("/sync/direction")
def set_sync_direction(
    request: Request,
    sync_direction: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = get_session_user_id(request)
    if not uid:
        return RedirectResponse(
            "/?flash=未登录&flash_err=1", status_code=302
        )
    user = db.get(User, uid)
    if not user:
        return RedirectResponse(
            "/?flash=会话无效&flash_err=1", status_code=302
        )
    direction = (sync_direction or "").strip()
    if direction not in VALID_SYNC_DIRECTIONS:
        return RedirectResponse(
            "/?flash=" + quote("无效的同步方向") + "&flash_err=1",
            status_code=302,
        )
    user.sync_direction = direction
    try:
        push_subscriptions.ensure_user_subscriptions(db, user)
    except Exception:
        log.exception("切换同步方向时更新推送订阅失败 user=%s", user.id)
    db.commit()
    labels = {
        DIR_FEISHU_TO_OUTLOOK: "飞书 → Outlook",
        DIR_OUTLOOK_TO_FEISHU: "Outlook → 飞书",
        DIR_BIDIRECTIONAL: "双向",
    }
    tip = ""
    if direction in (DIR_OUTLOOK_TO_FEISHU, DIR_BIDIRECTIONAL):
        tip = "（若此前仅授权只读，请断开并重新连接飞书以获取写权限）"
    msg = quote(f"已保存同步方向：{labels.get(direction, direction)}{tip}")
    return RedirectResponse(f"/?flash={msg}", status_code=302)
