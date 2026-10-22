"""Feishu (Lark) user OAuth — authorization code + refresh via v2 token API."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict
from urllib.parse import urlencode

import httpx

from .config import get_settings

log = logging.getLogger("auth_feishu")

AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"


class FeishuAuthError(RuntimeError):
    pass


def make_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(state: str) -> str:
    settings = get_settings()
    if not settings.feishu_app_id:
        raise FeishuAuthError("未配置 FEISHU_APP_ID")
    params = {
        "client_id": settings.feishu_app_id,
        "response_type": "code",
        "redirect_uri": settings.feishu_redirect_uri,
        "state": state,
        "scope": settings.feishu_scopes,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _token_request(body: dict) -> Dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            data = resp.json()
        except Exception as e:
            raise FeishuAuthError(
                f"飞书 token 响应非 JSON: {resp.status_code} {resp.text[:300]}"
            ) from e

    # v2 may return code==0 or OAuth-style without code field
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise FeishuAuthError(
            f"飞书换取令牌失败: code={data.get('code')} msg={data.get('error') or data.get('msg')}"
        )
    if "access_token" not in data:
        raise FeishuAuthError(f"飞书换取令牌失败（无 access_token）: {data}")
    return data


def exchange_code(code: str) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise FeishuAuthError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
    return _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": settings.feishu_app_id,
            "client_secret": settings.feishu_app_secret,
            "code": code,
            "redirect_uri": settings.feishu_redirect_uri,
        }
    )


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    settings = get_settings()
    return _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": settings.feishu_app_id,
            "client_secret": settings.feishu_app_secret,
            "refresh_token": refresh_token,
        }
    )


def fetch_user_info(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(USER_INFO_URL, headers=headers)
        try:
            data = resp.json()
        except Exception as e:
            raise FeishuAuthError(
                f"飞书用户信息非 JSON: {resp.status_code}"
            ) from e
    if data.get("code") not in (0, None):
        # Some deployments return data at top-level
        if "data" not in data and "open_id" not in data:
            raise FeishuAuthError(
                f"获取飞书用户信息失败: {data.get('code')} {data.get('msg')}"
            )
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    return inner or {}
