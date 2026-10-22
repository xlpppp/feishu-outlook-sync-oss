"""JSON API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..session_auth import get_session_user_id
from .. import tokens
from ..config import get_settings
from ..sync_service import sync_user

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health():
    return {"status": "ok"}


# Also expose at /health for load balancers
health_router = APIRouter(tags=["health"])


@health_router.get("/health")
def health_root():
    return {"status": "ok"}


def _require_user(request: Request, db: Session) -> User:
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录，请先连接 Outlook 或飞书")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="会话无效，请重新授权")
    return user


@router.get("/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    settings = get_settings()
    return {
        "id": user.id,
        "display_name": user.display_name,
        "ms_email": user.ms_email,
        "ms_connected": tokens.has_token(db, user.id, tokens.PROVIDER_MS),
        "feishu_open_id": user.feishu_open_id,
        "feishu_name": user.feishu_name,
        "feishu_connected": tokens.has_token(db, user.id, tokens.PROVIDER_FEISHU),
        "outlook_calendar_name": user.outlook_calendar_name
        or settings.outlook_calendar_name,
        "feishu_target_calendar_name": settings.feishu_sync_calendar_name,
        "sync_direction": user.sync_direction or "feishu_to_outlook",
        "sync_enabled": user.sync_enabled,
        "last_sync_at": user.last_sync_at.isoformat() if user.last_sync_at else None,
        "last_sync_status": user.last_sync_status,
        "last_sync_message": user.last_sync_message,
    }


@router.post("/sync/now")
def api_sync_now(
    request: Request,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    result = sync_user(db, user, dry_run=dry_run, trigger="manual")
    return {
        "ok": result.errors == 0,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "deleted": result.deleted,
        "errors": result.errors,
        "message": result.message,
        "direction": result.direction,
        "dry_run": result.dry_run,
    }


