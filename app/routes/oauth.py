"""OAuth start / callback / disconnect routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import auth_feishu, auth_ms, push_subscriptions, tokens
from ..config import get_settings
from ..db import get_db
from ..models import PUSH_PROVIDER_FEISHU, PUSH_PROVIDER_MS, User
from ..session_auth import (
    clear_session,
    get_session_user_id,
    set_session_user,
)

log = logging.getLogger("oauth")
router = APIRouter(prefix="/oauth", tags=["oauth"])

# In-memory OAuth state (single-process; OK for small deploys)
_oauth_states: dict[str, dict] = {}


def _safe_relative_next(next_path: Optional[str]) -> Optional[str]:
    """Allow only same-origin relative paths (reject //evil, https://, etc.)."""
    if not next_path:
        return None
    path = next_path.strip()
    if not path.startswith("/") or path.startswith("//"):
        return None
    if "://" in path:
        return None
    return path


def _flash_redirect(url: str, message: str, *, error: bool = False) -> RedirectResponse:
    # Encode flash in query for simplicity
    from urllib.parse import urlencode

    q = urlencode({"flash": message, "flash_err": "1" if error else "0"})
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}{q}", status_code=302)


def _get_or_create_session_user(request: Request, db: Session) -> Optional[User]:
    uid = get_session_user_id(request)
    if uid:
        return db.get(User, uid)
    return None


# ---------- Microsoft ----------


@router.get("/microsoft/start")
def ms_start(request: Request):
    settings = get_settings()
    if not settings.ms_client_id:
        return _flash_redirect("/", "服务未配置 MS_CLIENT_ID", error=True)
    state = auth_ms.make_oauth_state()
    _oauth_states[state] = {
        "provider": "microsoft",
        "uid": get_session_user_id(request),
    }
    try:
        url = auth_ms.build_auth_url(state)
    except Exception as e:
        return _flash_redirect("/", f"无法启动 Microsoft 授权: {e}", error=True)
    return RedirectResponse(url, status_code=302)


@router.get("/microsoft/callback")
def ms_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        return _flash_redirect(
            "/",
            f"Microsoft 授权取消/失败: {error_description or error}",
            error=True,
        )
    if not code or not state or state not in _oauth_states:
        return _flash_redirect("/", "Microsoft OAuth state 无效，请重试", error=True)
    meta = _oauth_states.pop(state, {})

    try:
        result = auth_ms.exchange_code(code)
        profile = auth_ms.fetch_profile(result["access_token"])
        oid, email, name = auth_ms.extract_oid_and_email(result, profile)
    except Exception as e:
        log.exception("MS callback failed")
        return _flash_redirect("/", f"Microsoft 授权失败: {e}", error=True)

    # Find or create user by ms_oid
    user = db.query(User).filter(User.ms_oid == oid).one_or_none()
    session_user = None
    if meta.get("uid"):
        session_user = db.get(User, meta["uid"])

    if user is None and session_user is not None:
        # Bind MS to existing session user (e.g. Feishu-first)
        if session_user.ms_oid and session_user.ms_oid != oid:
            return _flash_redirect(
                "/",
                "当前会话已绑定其他 Outlook 账户，请先退出",
                error=True,
            )
        user = session_user
        user.ms_oid = oid
        user.ms_email = email
        if not user.display_name:
            user.display_name = name
    elif user is None:
        user = User(ms_oid=oid, ms_email=email, display_name=name)
        db.add(user)
        db.flush()
    else:
        user.ms_email = email
        if not user.display_name:
            user.display_name = name
        # If session had another user, prefer MS identity
        if session_user and session_user.id != user.id:
            # Merge feishu from session if target has none
            if not user.feishu_open_id and session_user.feishu_open_id:
                user.feishu_open_id = session_user.feishu_open_id
                user.feishu_name = session_user.feishu_name
                # Move feishu token if present
                for t in list(session_user.tokens):
                    if t.provider == tokens.PROVIDER_FEISHU:
                        t.user_id = user.id

    settings = get_settings()
    if not user.outlook_calendar_name:
        user.outlook_calendar_name = settings.outlook_calendar_name

    expires_in = result.get("expires_in")
    refresh = result.get("refresh_token")
    tokens.upsert_token(
        db,
        user.id,
        tokens.PROVIDER_MS,
        access_token=result["access_token"],
        refresh_token=refresh,
        expires_in=expires_in,
        raw={k: v for k, v in result.items() if "token" not in k.lower()},
    )
    try:
        push_subscriptions.ensure_user_subscriptions(db, user)
    except Exception:
        log.exception("连接 Outlook 后创建推送订阅失败 user=%s", user.id)
    db.commit()

    resp = _flash_redirect("/", f"已连接 Outlook：{email or name}")
    set_session_user(resp, user.id)
    return resp


@router.post("/microsoft/disconnect")
@router.get("/microsoft/disconnect")
def ms_disconnect(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    if not uid:
        return _flash_redirect("/", "未登录", error=True)
    user = db.get(User, uid)
    if not user:
        return _flash_redirect("/", "用户不存在", error=True)
    try:
        push_subscriptions.cleanup_user_subscriptions(
            db, user, provider=PUSH_PROVIDER_MS
        )
    except Exception:
        log.exception("断开 Outlook 时清理推送订阅失败 user=%s", user.id)
    tokens.delete_token(db, user.id, tokens.PROVIDER_MS)
    user.ms_oid = None
    user.ms_email = None
    user.outlook_calendar_id = None
    db.commit()
    return _flash_redirect("/", "已断开 Outlook 连接")


# ---------- Feishu ----------


@router.get("/feishu/start")
def feishu_start(request: Request, next: Optional[str] = None):
    settings = get_settings()
    if not settings.feishu_app_id:
        return _flash_redirect("/", "服务未配置 FEISHU_APP_ID", error=True)
    state = auth_feishu.make_oauth_state()
    _oauth_states[state] = {
        "provider": "feishu",
        "uid": get_session_user_id(request),
        "next": _safe_relative_next(next),
    }
    try:
        url = auth_feishu.build_auth_url(state)
    except Exception as e:
        return _flash_redirect("/", f"无法启动飞书授权: {e}", error=True)
    return RedirectResponse(url, status_code=302)


@router.get("/feishu/callback")
def feishu_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        return _flash_redirect("/", f"飞书授权失败: {error}", error=True)
    if not code or not state or state not in _oauth_states:
        return _flash_redirect("/", "飞书 OAuth state 无效，请重试", error=True)
    meta = _oauth_states.pop(state, {})

    try:
        result = auth_feishu.exchange_code(code)
        info = auth_feishu.fetch_user_info(result["access_token"])
        open_id = str(info.get("open_id") or info.get("union_id") or "")
        name = str(info.get("name") or info.get("en_name") or open_id)
        if not open_id:
            raise auth_feishu.FeishuAuthError("无法获取飞书 open_id")
    except Exception as e:
        log.exception("Feishu callback failed")
        return _flash_redirect("/", f"飞书授权失败: {e}", error=True)

    user = db.query(User).filter(User.feishu_open_id == open_id).one_or_none()
    session_user = None
    if meta.get("uid"):
        session_user = db.get(User, meta["uid"])

    if user is None and session_user is not None:
        if session_user.feishu_open_id and session_user.feishu_open_id != open_id:
            return _flash_redirect(
                "/", "当前会话已绑定其他飞书账户，请先退出", error=True
            )
        user = session_user
        user.feishu_open_id = open_id
        user.feishu_name = name
        if not user.display_name:
            user.display_name = name
    elif user is None:
        user = User(feishu_open_id=open_id, feishu_name=name, display_name=name)
        db.add(user)
        db.flush()
    else:
        user.feishu_name = name
        if session_user and session_user.id != user.id:
            if not user.ms_oid and session_user.ms_oid:
                user.ms_oid = session_user.ms_oid
                user.ms_email = session_user.ms_email
                for t in list(session_user.tokens):
                    if t.provider == tokens.PROVIDER_MS:
                        t.user_id = user.id

    tokens.upsert_token(
        db,
        user.id,
        tokens.PROVIDER_FEISHU,
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token"),
        expires_in=result.get("expires_in"),
        raw={k: v for k, v in result.items() if "token" not in k.lower()},
    )
    try:
        push_subscriptions.ensure_user_subscriptions(db, user)
    except Exception:
        log.exception("连接飞书后创建推送订阅失败 user=%s", user.id)
    db.commit()

    dest = _safe_relative_next(meta.get("next")) or "/"
    resp = _flash_redirect(dest, f"已连接飞书：{name}")
    set_session_user(resp, user.id)
    return resp


@router.post("/feishu/disconnect")
@router.get("/feishu/disconnect")
def feishu_disconnect(request: Request, db: Session = Depends(get_db)):
    uid = get_session_user_id(request)
    if not uid:
        return _flash_redirect("/", "未登录", error=True)
    user = db.get(User, uid)
    if not user:
        return _flash_redirect("/", "用户不存在", error=True)
    try:
        push_subscriptions.cleanup_user_subscriptions(
            db, user, provider=PUSH_PROVIDER_FEISHU
        )
    except Exception:
        log.exception("断开飞书时清理推送订阅失败 user=%s", user.id)
    tokens.delete_token(db, user.id, tokens.PROVIDER_FEISHU)
    user.feishu_open_id = None
    user.feishu_name = None
    db.commit()
    return _flash_redirect("/", "已断开飞书连接")


@router.post("/logout")
@router.get("/logout")
def logout():
    resp = _flash_redirect("/", "已退出本地会话")
    clear_session(resp)
    return resp
