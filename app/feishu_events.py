"""Feishu event webhook crypto: AES decrypt + signature verify + challenge parse."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

log = logging.getLogger("feishu_events")

# Official event type for calendar event changes (after per-calendar subscription API)
EVENT_CALENDAR_EVENT_CHANGED = "calendar.calendar.event.changed_v4"


class FeishuEventError(RuntimeError):
    pass


def decrypt_encrypt_field(encrypt_key: str, encrypt_b64: str) -> str:
    """
    Decrypt Feishu Encrypt Key ciphertext.
    AES-256-CBC, key = SHA256(encrypt_key), IV = first 16 bytes, PKCS7 padding.
    Official sample: open.feishu.cn event subscription guide.
    """
    if not encrypt_key:
        raise FeishuEventError("缺少 FEISHU_EVENT_ENCRYPT_KEY，无法解密")
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    try:
        raw = base64.b64decode(encrypt_b64)
    except Exception as e:
        raise FeishuEventError("encrypt 字段不是合法 Base64") from e
    if len(raw) < 17:
        raise FeishuEventError("encrypt 密文过短")
    iv, ciphertext = raw[:16], raw[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    if not padded:
        raise FeishuEventError("解密结果为空")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16 or pad_len > len(padded):
        raise FeishuEventError("解密填充无效（密钥可能错误）")
    if padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise FeishuEventError("解密填充校验失败（密钥可能错误）")
    return padded[:-pad_len].decode("utf-8")


def verify_signature(
    *,
    timestamp: str,
    nonce: str,
    encrypt_key: str,
    body: bytes,
    signature: str,
) -> bool:
    """X-Lark-Signature = sha256(timestamp + nonce + encrypt_key + raw_body)."""
    if not signature or not encrypt_key:
        return False
    expected = hashlib.sha256(
        (timestamp + nonce + encrypt_key).encode("utf-8") + body
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event_payload(
    body: bytes,
    *,
    encrypt_key: str = "",
    verification_token: str = "",
    timestamp: str = "",
    nonce: str = "",
    signature: str = "",
) -> dict[str, Any]:
    """
    Parse Feishu webhook JSON (plain or encrypted).
    When Encrypt Key is configured and signature headers present, verify signature
    before decrypting.
    """
    if not body:
        raise FeishuEventError("空请求体")

    # Signature required when encrypt key set and signature header present
    if encrypt_key and signature:
        if not verify_signature(
            timestamp=timestamp or "",
            nonce=nonce or "",
            encrypt_key=encrypt_key,
            body=body,
            signature=signature,
        ):
            raise FeishuEventError("飞书事件签名校验失败")

    try:
        outer = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise FeishuEventError("请求体不是 JSON") from e
    if not isinstance(outer, dict):
        raise FeishuEventError("请求体必须是 JSON 对象")

    if "encrypt" in outer:
        if not encrypt_key:
            raise FeishuEventError("收到加密事件但未配置 FEISHU_EVENT_ENCRYPT_KEY")
        # Prefer signature when encrypt key is set; if no signature (challenge
        # before Encrypt Key saved), still try decrypt for url_verification.
        plain = decrypt_encrypt_field(encrypt_key, str(outer["encrypt"]))
        try:
            payload = json.loads(plain)
        except Exception as e:
            raise FeishuEventError("解密后不是 JSON") from e
        if not isinstance(payload, dict):
            raise FeishuEventError("解密后必须是 JSON 对象")
    else:
        payload = outer

    # Verification Token: schema 2.0 uses header.token; challenge uses top-level token
    token = payload.get("token")
    header = payload.get("header")
    if isinstance(header, dict) and header.get("token"):
        token = header.get("token")

    if verification_token and token and token != verification_token:
        raise FeishuEventError("Verification Token 不匹配")

    return payload


def is_url_verification(payload: dict[str, Any]) -> bool:
    if payload.get("type") == "url_verification":
        return True
    # Encrypted challenge may only expose challenge field after decrypt
    return "challenge" in payload and not _event_type(payload)


def challenge_response(payload: dict[str, Any]) -> dict[str, str]:
    challenge = payload.get("challenge")
    if challenge is None:
        raise FeishuEventError("url_verification 缺少 challenge")
    return {"challenge": str(challenge)}


def _event_type(payload: dict[str, Any]) -> Optional[str]:
    header = payload.get("header")
    if isinstance(header, dict) and header.get("event_type"):
        return str(header["event_type"])
    # Schema 1.0
    if payload.get("event") and payload.get("type"):
        return str(payload.get("type"))
    return None


def event_type(payload: dict[str, Any]) -> Optional[str]:
    return _event_type(payload)


def extract_calendar_event_change(
    payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Normalize calendar.calendar.event.changed_v4 into:
    {calendar_id, open_ids: [...], change_type?}
    """
    et = event_type(payload)
    if et != EVENT_CALENDAR_EVENT_CHANGED:
        return None
    ev = payload.get("event") or {}
    if not isinstance(ev, dict):
        return None
    calendar_id = ev.get("calendar_id")
    open_ids: list[str] = []
    for u in ev.get("user_id_list") or []:
        if isinstance(u, dict) and u.get("open_id"):
            open_ids.append(str(u["open_id"]))
    return {
        "calendar_id": str(calendar_id) if calendar_id else None,
        "open_ids": open_ids,
        "change_type": ev.get("change_type"),
        "calendar_event_id": ev.get("calendar_event_id"),
    }
