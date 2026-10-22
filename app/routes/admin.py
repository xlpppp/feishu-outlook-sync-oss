"""Admin: list users, toggle sync, unbind tokens, expand sync run logs."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import push_subscriptions, tokens
from ..config import get_settings
from ..db import get_db
from ..models import EventMapping, User
from ..session_auth import get_session_user_id
from ..sync_runs import list_recent_runs
from ..util import html_escape

log = logging.getLogger("admin")
router = APIRouter(tags=["admin"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

_TRIGGER_LABELS = {
    "poll": "轮询",
    "push": "推送",
    "manual": "手动",
    "admin": "管理",
}


def require_admin(request: Request, db: Session) -> User | Response:
    settings = get_settings()
    if not settings.admin_feishu_open_ids:
        return Response(status_code=404)
    uid = get_session_user_id(request)
    if not uid:
        return RedirectResponse(
            "/oauth/feishu/start?next=/admin", status_code=302
        )
    user = db.get(User, uid)
    if not user or not settings.is_admin_open_id(user.feishu_open_id):
        return Response("Forbidden", status_code=403)
    return user


def _format_dt(dt: datetime | None, tz_name: str) -> str:
    if dt is None:
        return "—"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _run_view(run, tz_name: str) -> dict:
    return {
        "started_display": _format_dt(run.started_at, tz_name),
        "trigger": run.trigger,
        "trigger_label": _TRIGGER_LABELS.get(run.trigger, run.trigger),
        "status": run.status,
        "message": run.message,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "deleted_count": run.deleted_count,
    }


@router.get("/admin", response_class=HTMLResponse)
def admin_index(
    request: Request,
    flash: str | None = None,
    flash_err: str | None = None,
    expand: int | None = None,
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    users = db.query(User).order_by(User.id.desc()).all()
    mapping_counts = dict(
        db.query(EventMapping.user_id, func.count(EventMapping.id))
        .group_by(EventMapping.user_id)
        .all()
    )
    settings = get_settings()
    tz_name = settings.timezone
    rows = []
    for u in users:
        recent = []
        if expand is not None and expand == u.id:
            recent = [
                _run_view(r, tz_name)
                for r in list_recent_runs(db, u.id, days=7)
            ]
        rows.append(
            {
                "user": u,
                "ms_connected": tokens.has_token(db, u.id, tokens.PROVIDER_MS),
                "feishu_connected": tokens.has_token(
                    db, u.id, tokens.PROVIDER_FEISHU
                ),
                "mapping_count": int(mapping_counts.get(u.id, 0)),
                "recent_runs": recent,
            }
        )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "admin": admin,
            "rows": rows,
            "expand_user_id": expand,
            "flash": flash,
            "flash_error": flash_err == "1",
            "outlook_target_calendar_name": settings.outlook_calendar_name,
            "feishu_target_calendar_name": settings.feishu_sync_calendar_name,
            "sync_interval": settings.sync_interval_minutes,
        },
    )


@router.get("/admin/users/{user_id}/sync-runs", response_class=HTMLResponse)
def admin_user_sync_runs(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Expand-on-demand HTML fragment of last 7 days of sync runs."""
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    target = db.get(User, user_id)
    if not target:
        return Response("用户不存在", status_code=404)
    settings = get_settings()
    runs = [
        _run_view(r, settings.timezone)
        for r in list_recent_runs(db, user_id, days=7)
    ]
    if not runs:
        return HTMLResponse(
            '<div class="admin-expand"><p class="muted" style="margin:0">'
            "近 7 天暂无同步记录</p></div>"
        )
    rows_html = []
    for run in runs:
        if run["status"] == "ok":
            badge = '<span class="badge ok">成功</span>'
        elif run["status"] == "partial":
            badge = '<span class="badge partial">部分</span>'
        else:
            badge = '<span class="badge err">失败</span>'
        msg = html_escape(run["message"] or "—")
        started = html_escape(run["started_display"])
        trigger_l = html_escape(run["trigger_label"])
        rows_html.append(
            "<tr>"
            f'<td class="cell-ellipsis" title="{started}">{started}</td>'
            f"<td>{trigger_l}</td>"
            f"<td>{badge}</td>"
            f'<td class="cell-ellipsis">+{run["created_count"]} / '
            f'~{run["updated_count"]} / −{run["deleted_count"]}</td>'
            f'<td class="cell-ellipsis" title="{msg}">{msg}</td>'
            "</tr>"
        )
    body = (
        '<div class="admin-expand"><h3>近 7 天同步记录</h3>'
        '<table class="admin-runs"><thead><tr>'
        '<th class="col-time">开始时间</th>'
        '<th class="col-trigger">触发</th>'
        '<th class="col-status">状态</th>'
        '<th class="col-counts">计数</th>'
        "<th>摘要</th>"
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div>"
    )
    return HTMLResponse(body)


@router.post("/admin/users/{user_id}/sync")
def admin_toggle_sync(
    user_id: int,
    request: Request,
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    target = db.get(User, user_id)
    if not target:
        return RedirectResponse(
            "/admin?flash=" + quote("用户不存在") + "&flash_err=1", status_code=302
        )
    target.sync_enabled = enabled in ("1", "true", "on")
    admin_id, target_id = admin.id, target.id
    enabled_now = target.sync_enabled
    try:
        if enabled_now:
            push_subscriptions.ensure_user_subscriptions(db, target)
        else:
            push_subscriptions.cleanup_user_subscriptions(db, target)
    except Exception:
        log.exception(
            "admin toggle sync failed admin=%s user=%s", admin_id, target_id
        )
    db.commit()
    log.info(
        "admin_toggle_sync admin_user_id=%s target_user_id=%s enabled=%s",
        admin_id,
        target_id,
        enabled_now,
    )
    return RedirectResponse(
        "/admin?flash=" + quote("已更新自动同步"), status_code=302
    )


@router.post("/admin/users/{user_id}/unbind")
def admin_unbind(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    target = db.get(User, user_id)
    if not target:
        return RedirectResponse(
            "/admin?flash=" + quote("用户不存在") + "&flash_err=1", status_code=302
        )
    admin_id, target_id = admin.id, target.id
    try:
        push_subscriptions.cleanup_user_subscriptions(db, target)
    except Exception:
        log.exception(
            "admin unbind cleanup push failed admin=%s user=%s",
            admin_id,
            target_id,
        )
    tokens.delete_token(db, target_id, tokens.PROVIDER_MS)
    tokens.delete_token(db, target_id, tokens.PROVIDER_FEISHU)
    db.commit()
    log.info(
        "admin_unbind admin_user_id=%s target_user_id=%s", admin_id, target_id
    )
    return RedirectResponse(
        "/admin?flash=" + quote("已解除登录绑定（仅清除 Token）"),
        status_code=302,
    )
