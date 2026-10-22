"""SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Sync direction values (persisted on users.sync_direction)
DIR_FEISHU_TO_OUTLOOK = "feishu_to_outlook"
DIR_OUTLOOK_TO_FEISHU = "outlook_to_feishu"
DIR_BIDIRECTIONAL = "bidirectional"
VALID_SYNC_DIRECTIONS = (
    DIR_FEISHU_TO_OUTLOOK,
    DIR_OUTLOOK_TO_FEISHU,
    DIR_BIDIRECTIONAL,
)

# Event mapping origin / leg
ORIGIN_F2O = "f2o"
ORIGIN_O2F = "o2f"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ms_oid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    ms_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    feishu_open_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    feishu_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outlook_calendar_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outlook_calendar_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_direction: Mapped[str] = mapped_column(
        String(64), default=DIR_FEISHU_TO_OUTLOOK, nullable=False
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tokens: Mapped[list["Token"]] = relationship(
        "Token", back_populates="user", cascade="all, delete-orphan"
    )
    event_mappings: Mapped[list["EventMapping"]] = relationship(
        "EventMapping", back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[list["SyncRun"]] = relationship(
        "SyncRun", back_populates="user", cascade="all, delete-orphan"
    )


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_token_user_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # microsoft|feishu
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_json_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="tokens")


class EventMapping(Base):
    __tablename__ = "event_mappings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "feishu_event_id", name="uq_mapping_user_feishu_event"
        ),
        UniqueConstraint(
            "user_id", "outlook_event_id", name="uq_mapping_user_outlook_event"
        ),
        Index("ix_mapping_user", "user_id"),
        Index("ix_mapping_user_direction", "user_id", "direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feishu_event_id: Mapped[str] = mapped_column(String(256), nullable=False)
    outlook_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which sync leg created this link: f2o | o2f
    direction: Mapped[str] = mapped_column(
        String(8), default=ORIGIN_F2O, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="event_mappings")


# Push webhook subscription providers
PUSH_PROVIDER_FEISHU = "feishu"
PUSH_PROVIDER_MS = "ms"


class PushSubscription(Base):
    """Persisted Feishu / Microsoft Graph webhook subscription state."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "resource",
            name="uq_push_user_provider_resource",
        ),
        Index("ix_push_subscription_id", "subscription_id"),
        Index("ix_push_expires_at", "expires_at"),
        Index("ix_push_user_provider", "user_id", "provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # feishu | ms
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    # Feishu calendar_id, or Graph resource path (e.g. /me/events)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    # Graph subscription id; Feishu uses calendar_id (no separate id from API)
    subscription_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    client_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_meta: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="push_subscriptions")


# Sync run log trigger / status
TRIGGER_POLL = "poll"
TRIGGER_PUSH = "push"
TRIGGER_MANUAL = "manual"
TRIGGER_ADMIN = "admin"
VALID_SYNC_TRIGGERS = (
    TRIGGER_POLL,
    TRIGGER_PUSH,
    TRIGGER_MANUAL,
    TRIGGER_ADMIN,
)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_PARTIAL = "partial"
VALID_SYNC_STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_PARTIAL)


class SyncRun(Base):
    """One completed sync attempt for a user (retained ~7 days)."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_user_started", "user_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # poll | push | manual | admin
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    # ok | error | partial
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="sync_runs")
