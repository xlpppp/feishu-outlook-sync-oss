"""Environment-based configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env from project root if present
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _split_scopes(raw: str) -> List[str]:
    return [s for s in raw.replace(",", " ").split() if s]


class Settings:
    def __init__(self) -> None:
        self.public_base_url: str = os.getenv(
            "PUBLIC_BASE_URL", "http://127.0.0.1:8000"
        ).rstrip("/")
        self.secret_key: str = os.getenv("SECRET_KEY", "dev-insecure-change-me")
        self.token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")

        self.ms_client_id: str = os.getenv("MS_CLIENT_ID", "")
        self.ms_client_secret: str = os.getenv("MS_CLIENT_SECRET", "")
        self.ms_authority: str = os.getenv(
            "MS_AUTHORITY", "https://login.microsoftonline.com/consumers"
        )
        self.ms_scopes: List[str] = _split_scopes(
            os.getenv(
                "MS_SCOPES", "Calendars.ReadWrite User.Read"
            )
        )

        self.feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
        self.feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
        # calendar:calendar = Feishu write scope (create calendar + create/patch/delete events)
        # calendar:calendar:readonly kept for explicit read; offline_access for refresh_token
        # OAuth scope 必须与开放平台「权限管理」里的 key 完全一致，否则 20043。
        # 勿用已弃用/未开通的 key（如部分租户上 calendar:calendar:readonly 会 20043）。
        self.feishu_scopes: str = os.getenv(
            "FEISHU_SCOPES",
            "calendar:calendar calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete offline_access",
        )

        self.outlook_calendar_name: str = os.getenv(
            "OUTLOOK_CALENDAR_NAME", "Feishu Sync"
        )
        self.feishu_sync_calendar_name: str = os.getenv(
            "FEISHU_SYNC_CALENDAR_NAME", "Outlook Sync"
        )
        # Skip Feishu subscribed calendars (role=reader / free_busy_reader) for F→O
        self.skip_subscribed_calendars: bool = _bool(
            os.getenv("SKIP_SUBSCRIBED_CALENDARS"), default=True
        )
        self.sync_interval_minutes: int = int(
            os.getenv("SYNC_INTERVAL_MINUTES", "15")
        )
        self.sync_window_past_days: int = int(
            os.getenv("SYNC_WINDOW_PAST_DAYS", "7")
        )
        self.sync_window_future_days: int = int(
            os.getenv("SYNC_WINDOW_FUTURE_DAYS", "60")
        )
        self.timezone: str = os.getenv("TIMEZONE", "Asia/Shanghai")

        db = os.getenv("DATABASE_URL", "")
        if not db:
            data_dir = _ROOT / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db = f"sqlite:///{data_dir / 'sync.db'}"
        self.database_url: str = db

        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.cookie_secure: bool = _bool(os.getenv("COOKIE_SECURE"), default=True)

        raw_admins = os.getenv("ADMIN_FEISHU_OPEN_IDS", "")
        self.admin_feishu_open_ids: list[str] = [
            p.strip() for p in raw_admins.replace(";", ",").split(",") if p.strip()
        ]

        # Daily SQLite backup (inside container; files live on the Docker volume)
        self.backup_enabled: bool = _bool(os.getenv("BACKUP_ENABLED"), default=True)
        self.backup_dir: str = os.getenv("BACKUP_DIR", "/data/backups")
        self.backup_keep_days: int = int(os.getenv("BACKUP_KEEP_DAYS", "14"))
        self.backup_hour: int = int(os.getenv("BACKUP_HOUR", "3"))  # local TIMEZONE
        self.backup_minute: int = int(os.getenv("BACKUP_MINUTE", "15"))

        # Near-real-time push (Feishu event subscription + Graph change notifications)
        # PUSH_SYNC_ENABLED: explicit true/false; if unset, auto-on when secrets exist
        self._push_sync_enabled_raw: str | None = os.getenv("PUSH_SYNC_ENABLED")
        self.feishu_event_encrypt_key: str = os.getenv(
            "FEISHU_EVENT_ENCRYPT_KEY", ""
        ).strip()
        self.feishu_event_verification_token: str = os.getenv(
            "FEISHU_EVENT_VERIFICATION_TOKEN", ""
        ).strip()
        self.graph_webhook_client_state: str = os.getenv(
            "GRAPH_WEBHOOK_CLIENT_STATE", ""
        ).strip()
        self.push_debounce_seconds: int = int(
            os.getenv("PUSH_DEBOUNCE_SECONDS", "20")
        )
        # Renew Graph subscriptions this many hours before expiry
        self.graph_subscription_renew_hours: int = int(
            os.getenv("GRAPH_SUBSCRIPTION_RENEW_HOURS", "24")
        )

    @property
    def ms_redirect_uri(self) -> str:
        return f"{self.public_base_url}/oauth/microsoft/callback"

    @property
    def feishu_redirect_uri(self) -> str:
        return f"{self.public_base_url}/oauth/feishu/callback"

    @property
    def feishu_webhook_url(self) -> str:
        return f"{self.public_base_url}/webhooks/feishu"

    @property
    def microsoft_webhook_url(self) -> str:
        return f"{self.public_base_url}/webhooks/microsoft"

    @property
    def push_sync_enabled(self) -> bool:
        """Master switch: explicit env wins; else auto-on when any push secret set."""
        if self._push_sync_enabled_raw is not None:
            return _bool(self._push_sync_enabled_raw, default=False)
        return bool(
            self.feishu_event_encrypt_key
            or self.feishu_event_verification_token
            or self.graph_webhook_client_state
        )

    @property
    def feishu_push_configured(self) -> bool:
        return bool(
            self.feishu_event_encrypt_key or self.feishu_event_verification_token
        )

    @property
    def graph_push_configured(self) -> bool:
        return bool(self.graph_webhook_client_state)

    def feishu_push_active(self) -> bool:
        return self.push_sync_enabled and self.feishu_push_configured

    def graph_push_active(self) -> bool:
        return self.push_sync_enabled and self.graph_push_configured

    def needs_feishu_write(self, sync_direction: str) -> bool:
        """True when direction writes into Feishu (needs calendar:calendar write)."""
        return sync_direction in ("outlook_to_feishu", "bidirectional")

    def is_admin_open_id(self, open_id: str | None) -> bool:
        if not open_id or not self.admin_feishu_open_ids:
            return False
        return open_id.strip() in self.admin_feishu_open_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()
