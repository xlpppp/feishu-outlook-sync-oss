#!/usr/bin/env python3
"""Import modules and verify FastAPI routes load."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "smoke-test-secret")
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY",
    "ZPBgNpw_XZrZnGRDNgpCP5Y1fi-hCcHpWvuVZli3FLo=",
)
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'smoke.db'}"
)


def main() -> int:
    from app.config import get_settings
    from app.crypto import encrypt_str, decrypt_str
    from app.db import init_db, get_engine, session_scope
    from app.main import create_app
    from app.models import (
        DIR_FEISHU_TO_OUTLOOK,
        DIR_OUTLOOK_TO_FEISHU,
        DIR_BIDIRECTIONAL,
        ORIGIN_F2O,
        User,
        EventMapping,
    )
    from app.util import (
        compute_event_hash,
        sync_window,
        feishu_event_to_graph_payload,
        graph_event_to_feishu_payload,
        outlook_event_content_hash,
    )
    from app import feishu_api, graph_api, sync_service

    settings = get_settings()
    assert settings.public_base_url
    assert settings.feishu_sync_calendar_name == "Outlook Sync" or settings.feishu_sync_calendar_name
    assert "calendar:calendar" in settings.feishu_scopes
    assert settings.needs_feishu_write(DIR_OUTLOOK_TO_FEISHU)
    assert settings.needs_feishu_write(DIR_BIDIRECTIONAL)
    assert not settings.needs_feishu_write(DIR_FEISHU_TO_OUTLOOK)

    enc = encrypt_str("hello-token")
    assert decrypt_str(enc) == "hello-token"

    # Fresh DB + migration path: create, then re-init (ALTER no-op)
    smoke_db = ROOT / "data" / "smoke.db"
    if smoke_db.exists():
        smoke_db.unlink()
    init_db()
    init_db()  # second pass exercises migrate_schema IF NOT EXISTS paths

    # Verify columns exist
    with get_engine().connect() as conn:
        from sqlalchemy import text

        cols_u = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        cols_m = {
            r[1] for r in conn.execute(text("PRAGMA table_info(event_mappings)")).fetchall()
        }
        assert "sync_direction" in cols_u
        assert "direction" in cols_m

    h = compute_event_hash("t", "a", "b", "c", "d")
    assert len(h) == 64

    start, end = sync_window(7, 60, "Asia/Shanghai")
    assert end > start

    payload = feishu_event_to_graph_payload(
        {
            "summary": "测试",
            "start_time": {
                "timestamp": "1729332000",
                "timezone": "Asia/Shanghai",
            },
            "end_time": {
                "timestamp": "1729335600",
                "timezone": "Asia/Shanghai",
            },
            "location": {"name": "会议室"},
        },
        default_tz="Asia/Shanghai",
    )
    assert payload["subject"] == "测试"
    assert "start" in payload and "end" in payload

    # Graph → Feishu mapping
    g_ev = {
        "id": "oid-1",
        "subject": "Outlook 会议",
        "start": {"dateTime": "2026-10-20T10:00:00", "timeZone": "Asia/Shanghai"},
        "end": {"dateTime": "2026-10-20T11:00:00", "timeZone": "Asia/Shanghai"},
        "location": {"displayName": "Room A"},
        "bodyPreview": "议程",
        "body": {"contentType": "text", "content": "议程"},
        "isCancelled": False,
        "isAllDay": False,
        "showAs": "busy",
    }
    f_payload = graph_event_to_feishu_payload(g_ev, default_tz="Asia/Shanghai")
    assert f_payload["summary"] == "Outlook 会议"
    assert "timestamp" in f_payload["start_time"]
    assert f_payload["location"]["name"] == "Room A"
    oh = outlook_event_content_hash(g_ev, "Asia/Shanghai")
    assert len(oh) == 64

    # API symbols exist
    assert settings.skip_subscribed_calendars is True

    # Subscribed calendar filter (Feishu role=reader / free_busy_reader)
    sample = [
        {"calendar_id": "pri", "type": "primary", "role": "owner", "summary": "Me"},
        {
            "calendar_id": "sub1",
            "type": "shared",
            "role": "reader",
            "summary": "同事订阅日历",
        },
        {
            "calendar_id": "guest",
            "type": "shared",
            "role": "free_busy_reader",
            "summary": "仅忙闲",
        },
        {"calendar_id": "own", "type": "shared", "role": "owner", "summary": "我的共享"},
    ]
    assert feishu_api.is_subscribed_calendar(sample[1])
    assert feishu_api.is_subscribed_calendar(sample[2])
    assert not feishu_api.is_subscribed_calendar(sample[0])
    kept = feishu_api.filter_calendars_for_sync(sample, skip_subscribed=True)
    assert [c["calendar_id"] for c in kept] == ["pri", "own"]
    assert feishu_api.primary_calendar_id(sample, skip_subscribed=True) == "pri"
    # If only subscribed calendars exist, must not fall back onto them
    only_sub = [sample[1], sample[2]]
    assert feishu_api.primary_calendar_id(only_sub, skip_subscribed=True) is None
    assert feishu_api.primary_calendar_id(only_sub, skip_subscribed=False) == "sub1"

    assert callable(feishu_api.ensure_named_calendar)
    assert callable(feishu_api.create_event)
    assert callable(feishu_api.patch_event)
    assert callable(feishu_api.delete_event)
    assert callable(feishu_api.subscribe_calendar_events)
    assert callable(feishu_api.unsubscribe_calendar_events)
    assert callable(graph_api.get_default_calendar)
    assert callable(graph_api.list_events)
    assert callable(graph_api.create_subscription)
    assert callable(sync_service._sync_feishu_to_outlook)
    assert callable(sync_service._sync_outlook_to_feishu)

    # Feishu calendars eligible for event subscription: skip subscribed + target name
    from app import feishu_events, push_debounce
    from app.models import PushSubscription

    sub_cals = [
        {"calendar_id": "pri", "type": "primary", "role": "owner", "summary": "Me"},
        {
            "calendar_id": "sub1",
            "type": "shared",
            "role": "reader",
            "summary": "同事订阅日历",
        },
        {
            "calendar_id": "target",
            "type": "shared",
            "role": "owner",
            "summary": "Outlook Sync",
        },
    ]
    for_sub = feishu_api.calendars_for_event_subscription(
        sub_cals, exclude_calendar_name="Outlook Sync", skip_subscribed=True
    )
    assert [c["calendar_id"] for c in for_sub] == ["pri"]

    # Debounce helper clamps to 15–30
    assert push_debounce.debounce_delay_seconds(5) == 15
    assert push_debounce.debounce_delay_seconds(40) == 30
    assert push_debounce.debounce_delay_seconds(20) == 20

    # Feishu challenge echo (plain)
    challenge_body = b'{"challenge":"abc123","token":"vt","type":"url_verification"}'
    parsed = feishu_events.parse_event_payload(
        challenge_body, verification_token="vt"
    )
    assert feishu_events.is_url_verification(parsed)
    assert feishu_events.challenge_response(parsed) == {"challenge": "abc123"}

    # Official Encrypt Key sample decrypts to "hello world"
    plain = feishu_events.decrypt_encrypt_field(
        "test key", "P37w+VZImNgPEO1RBhJ6RtKl7n6zymIbEG1pReEzghk="
    )
    assert plain == "hello world"

    # Persist user with default direction + push_subscriptions table
    with session_scope() as db:
        u = User(display_name="smoke", sync_direction=DIR_FEISHU_TO_OUTLOOK)
        db.add(u)
        db.flush()
        assert u.sync_direction == DIR_FEISHU_TO_OUTLOOK
        m = EventMapping(
            user_id=u.id,
            feishu_event_id="f1",
            outlook_event_id="o1",
            content_hash=h,
            direction=ORIGIN_F2O,
        )
        db.add(m)
        ps = PushSubscription(
            user_id=u.id,
            provider="feishu",
            resource="pri",
            subscription_id="pri",
        )
        db.add(ps)

    with get_engine().connect() as conn:
        from sqlalchemy import text

        cols_p = {
            r[1]
            for r in conn.execute(text("PRAGMA table_info(push_subscriptions)")).fetchall()
        }
        assert "subscription_id" in cols_p
        assert "expires_at" in cols_p
        assert "client_state" in cols_p

    # Enable push secrets for webhook smoke (clear cached settings)
    os.environ["FEISHU_EVENT_VERIFICATION_TOKEN"] = "vt-smoke"
    os.environ["GRAPH_WEBHOOK_CLIENT_STATE"] = "graph-state-smoke"
    os.environ["PUSH_SYNC_ENABLED"] = "true"
    get_settings.cache_clear()

    app = create_app()
    paths = set(app.openapi()["paths"].keys())
    required = {
        "/health",
        "/",
        "/oauth/microsoft/start",
        "/oauth/microsoft/callback",
        "/oauth/feishu/start",
        "/oauth/feishu/callback",
        "/api/me",
        "/api/sync/now",
        "/api/sync/direction",
        "/sync/direction",
        "/webhooks/feishu",
        "/webhooks/microsoft",
    }
    missing = required - paths
    if missing:
        print("MISSING ROUTES:", missing)
        print("ALL:", sorted(paths))
        return 1

    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200 and r.json().get("status") == "ok"
            r2 = client.get("/")
            assert r2.status_code == 200
            assert "飞书" in r2.text
            assert "同步方向" in r2.text
            assert "Outlook Sync" in r2.text or "feishu_target" in r2.text.lower() or "Outlook Sync" in r2.text
            # Unauthenticated direction save → redirect with flash
            r3 = client.post(
                "/api/sync/direction",
                data={"sync_direction": DIR_BIDIRECTIONAL},
                follow_redirects=False,
            )
            assert r3.status_code in (302, 303)

            # Feishu challenge (no session cookie)
            r4 = client.post(
                "/webhooks/feishu",
                json={
                    "challenge": "chal-99",
                    "token": "vt-smoke",
                    "type": "url_verification",
                },
            )
            assert r4.status_code == 200
            assert r4.json().get("challenge") == "chal-99"

            # Graph validationToken handshake → plain text echo
            r5 = client.post(
                "/webhooks/microsoft",
                params={"validationToken": "validate-me-42"},
            )
            assert r5.status_code == 200
            assert r5.text == "validate-me-42"
            assert "application/json" not in (r5.headers.get("content-type") or "")
    except Exception as e:
        print("TestClient warning:", e)
        raise

    print("smoke_check OK")
    print("  openapi paths:", len(paths))
    print("  required ok:", sorted(required))
    print("  feishu_scopes:", settings.feishu_scopes)
    print("  feishu_sync_calendar_name:", settings.feishu_sync_calendar_name)
    print("  push_sync_enabled:", get_settings().push_sync_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
