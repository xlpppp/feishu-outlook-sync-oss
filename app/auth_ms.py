"""Microsoft OAuth (personal / consumers) via MSAL confidential client."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx
import msal

from .config import get_settings

log = logging.getLogger("auth_ms")

GRAPH_ME = "https://graph.microsoft.com/v1.0/me"


class MsAuthError(RuntimeError):
    pass

# MSAL 会自动附加 OIDC 保留 scope，传入会直接报错：
# "You cannot use any scope value that is reserved"
_MSAL_RESERVED_SCOPES = frozenset({"offline_access", "openid", "profile"})


def _msal_scopes(scopes: list[str] | None = None) -> list[str]:
    settings = get_settings()
    raw = list(scopes if scopes is not None else settings.ms_scopes)
    filtered = [s for s in raw if s and s not in _MSAL_RESERVED_SCOPES]
    if not filtered:
        raise MsAuthError("MS_SCOPES 过滤保留项后为空，请至少保留 Calendars.ReadWrite")
    return filtered


def _cca() -> msal.ConfidentialClientApplication:
    settings = get_settings()
    if not settings.ms_client_id:
        raise MsAuthError("未配置 MS_CLIENT_ID")
    if not settings.ms_client_secret:
        raise MsAuthError("未配置 MS_CLIENT_SECRET（机密客户端）")
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=settings.ms_authority,
    )


def make_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(state: str) -> str:
    """Build authorize URL. Prefer MSAL; fall back to manual URL."""
    settings = get_settings()
    try:
        app = _cca()
        return app.get_authorization_request_url(
            scopes=_msal_scopes(),
            state=state,
            redirect_uri=settings.ms_redirect_uri,
            prompt="select_account",
        )
    except MsAuthError:
        # Public client + PKCE fallback path not fully implemented here;
        # still build authorize URL for confidential apps missing secret during docs.
        scopes = _msal_scopes()
        # 手写授权 URL 时显式带上 offline_access（MSAL 路径由库自动附加）
        scope_str = " ".join(scopes + ["offline_access"])
        params = {
            "client_id": settings.ms_client_id,
            "response_type": "code",
            "redirect_uri": settings.ms_redirect_uri,
            "response_mode": "query",
            "scope": scope_str,
            "state": state,
            "prompt": "select_account",
        }
        base = settings.ms_authority.rstrip("/") + "/oauth2/v2.0/authorize"
        return f"{base}?{urlencode(params)}"


def exchange_code(code: str) -> Dict[str, Any]:
    settings = get_settings()
    app = _cca()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=_msal_scopes(),
        redirect_uri=settings.ms_redirect_uri,
    )
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or result
        raise MsAuthError(f"Microsoft 换取令牌失败: {err}")
    return result


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    settings = get_settings()
    app = _cca()
    result = app.acquire_token_by_refresh_token(
        refresh_token=refresh_token,
        scopes=_msal_scopes(),
    )
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or result
        raise MsAuthError(f"Microsoft 刷新令牌失败: {err}")
    return result


def fetch_profile(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(GRAPH_ME, headers=headers)
        if resp.status_code >= 400:
            raise MsAuthError(f"获取 Microsoft 用户信息失败: {resp.status_code} {resp.text}")
        return resp.json()


def extract_oid_and_email(token_result: dict, profile: Optional[dict] = None) -> Tuple[str, str, str]:
    """Return (oid, email, display_name)."""
    claims = token_result.get("id_token_claims") or {}
    oid = claims.get("oid") or claims.get("sub") or ""
    email = (
        claims.get("preferred_username")
        or claims.get("email")
        or (profile or {}).get("mail")
        or (profile or {}).get("userPrincipalName")
        or ""
    )
    name = claims.get("name") or (profile or {}).get("displayName") or email or oid
    if not oid and profile:
        # Graph /me does not return oid; use id as fallback key for personal
        oid = profile.get("id") or ""
    if not oid:
        raise MsAuthError("无法从令牌中解析用户 oid/sub")
    return str(oid), str(email), str(name)
