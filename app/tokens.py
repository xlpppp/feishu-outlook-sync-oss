"""Persist / load encrypted OAuth tokens per user."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from . import auth_feishu, auth_ms
from .crypto import decrypt_str, encrypt_str
from .models import Token, User

log = logging.getLogger("tokens")

PROVIDER_MS = "microsoft"
PROVIDER_FEISHU = "feishu"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_token(
    db: Session,
    user_id: int,
    provider: str,
    *,
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],
    raw: Optional[dict] = None,
) -> Token:
    row = (
        db.query(Token)
        .filter(Token.user_id == user_id, Token.provider == provider)
        .one_or_none()
    )
    if row is None:
        row = Token(user_id=user_id, provider=provider)
        db.add(row)

    row.access_token_enc = encrypt_str(access_token)
    if refresh_token:
        row.refresh_token_enc = encrypt_str(refresh_token)
    if expires_in:
        row.expires_at = _utcnow() + timedelta(seconds=int(expires_in) - 60)
    elif raw and raw.get("expires_in"):
        row.expires_at = _utcnow() + timedelta(seconds=int(raw["expires_in"]) - 60)
    if raw is not None:
        # Never store plaintext tokens in raw — scrub
        scrubbed = {
            k: ("***" if "token" in k.lower() else v)
            for k, v in raw.items()
            if k not in ("access_token", "refresh_token", "id_token")
        }
        row.raw_json_enc = encrypt_str(json.dumps(scrubbed, ensure_ascii=False))
    row.updated_at = _utcnow()
    db.flush()
    return row


def delete_token(db: Session, user_id: int, provider: str) -> bool:
    row = (
        db.query(Token)
        .filter(Token.user_id == user_id, Token.provider == provider)
        .one_or_none()
    )
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def has_token(db: Session, user_id: int, provider: str) -> bool:
    return (
        db.query(Token)
        .filter(Token.user_id == user_id, Token.provider == provider)
        .count()
        > 0
    )


def get_valid_access_token(db: Session, user: User, provider: str) -> str:
    row = (
        db.query(Token)
        .filter(Token.user_id == user.id, Token.provider == provider)
        .one_or_none()
    )
    if not row or not row.access_token_enc:
        raise RuntimeError(f"用户未连接 {provider}")

    access = decrypt_str(row.access_token_enc) or ""
    expires = row.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    still_valid = expires and expires > _utcnow() + timedelta(seconds=30)
    if still_valid and access:
        return access

    # Refresh
    refresh = decrypt_str(row.refresh_token_enc) if row.refresh_token_enc else None
    if not refresh:
        raise RuntimeError(f"{provider} 令牌已过期且无 refresh_token，请重新授权")

    if provider == PROVIDER_MS:
        result = auth_ms.refresh_access_token(refresh)
        expires_in = result.get("expires_in")
        new_refresh = result.get("refresh_token") or refresh
        upsert_token(
            db,
            user.id,
            PROVIDER_MS,
            access_token=result["access_token"],
            refresh_token=new_refresh,
            expires_in=expires_in,
            raw={k: v for k, v in result.items() if k != "access_token"},
        )
        db.commit()
        return result["access_token"]

    if provider == PROVIDER_FEISHU:
        result = auth_feishu.refresh_access_token(refresh)
        expires_in = result.get("expires_in")
        # Feishu refresh_token is single-use — always store new one
        new_refresh = result.get("refresh_token") or refresh
        upsert_token(
            db,
            user.id,
            PROVIDER_FEISHU,
            access_token=result["access_token"],
            refresh_token=new_refresh,
            expires_in=expires_in,
            raw={k: v for k, v in result.items() if "token" not in k.lower()},
        )
        db.commit()
        return result["access_token"]

    raise RuntimeError(f"未知 provider: {provider}")
