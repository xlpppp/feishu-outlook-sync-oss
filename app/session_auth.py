"""Signed cookie session helpers."""

from __future__ import annotations

from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings

COOKIE_NAME = "fos_session"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="fos-session-v1")


def set_session_user(response: Response, user_id: int) -> None:
    settings = get_settings()
    token = _serializer().dumps({"uid": user_id})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * 90,  # 90 days
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def get_session_user_id(request: Request) -> Optional[int]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
    except BadSignature:
        return None
    uid = data.get("uid")
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None
