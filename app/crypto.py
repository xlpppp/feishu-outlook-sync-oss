"""Fernet encryption for OAuth tokens at rest."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

log = logging.getLogger("crypto")


class CryptoError(RuntimeError):
    pass


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().token_encryption_key.strip()
    if not key:
        # Dev fallback — generate ephemeral (tokens won't survive restart)
        log.warning(
            "TOKEN_ENCRYPTION_KEY 未设置，使用临时密钥（重启后已存 token 无法解密）。"
            "生产环境必须配置稳定 Fernet 密钥。"
        )
        key = Fernet.generate_key().decode()
        return Fernet(key.encode() if isinstance(key, str) else key)
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as e:
        raise CryptoError(f"无效的 TOKEN_ENCRYPTION_KEY: {e}") from e


def encrypt_str(plain: Optional[str]) -> Optional[str]:
    if plain is None:
        return None
    if plain == "":
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_str(cipher: Optional[str]) -> Optional[str]:
    if cipher is None:
        return None
    if cipher == "":
        return ""
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise CryptoError(
            "无法解密 token（密钥是否变更？请重新授权）"
        ) from e
