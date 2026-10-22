"""Helpers for sync_runs: record, list (7-day window), purge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import (
    VALID_SYNC_STATUSES,
    VALID_SYNC_TRIGGERS,
    SyncRun,
)

DEFAULT_RETENTION_DAYS = 7
DEFAULT_LIST_LIMIT = 100
_MESSAGE_MAX = 2000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_sync_run(
    db: Session,
    user_id: int,
    *,
    trigger: str,
    status: str,
    message: str | None = None,
    created: int = 0,
    updated: int = 0,
    deleted: int = 0,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> SyncRun:
    """Insert one SyncRun row. Validates trigger/status at write time."""
    trigger = (trigger or "").strip()
    status = (status or "").strip()
    if trigger not in VALID_SYNC_TRIGGERS:
        raise ValueError(f"invalid sync trigger: {trigger!r}")
    if status not in VALID_SYNC_STATUSES:
        raise ValueError(f"invalid sync status: {status!r}")

    now = _utcnow()
    started = started_at or now
    finished = finished_at if finished_at is not None else now
    row = SyncRun(
        user_id=user_id,
        started_at=started,
        finished_at=finished,
        trigger=trigger,
        status=status,
        message=(message or "")[:_MESSAGE_MAX] or None,
        created_count=int(created or 0),
        updated_count=int(updated or 0),
        deleted_count=int(deleted or 0),
    )
    db.add(row)
    db.flush()
    return row


def list_recent_runs(
    db: Session,
    user_id: int,
    *,
    days: int = DEFAULT_RETENTION_DAYS,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[SyncRun]:
    """Runs for user with started_at within the last `days`, newest first."""
    cutoff = _utcnow() - timedelta(days=max(1, int(days)))
    q = (
        db.query(SyncRun)
        .filter(SyncRun.user_id == user_id, SyncRun.started_at >= cutoff)
        .order_by(SyncRun.started_at.desc())
        .limit(max(1, int(limit)))
    )
    return list(q.all())


def purge_old_runs(
    db: Session, *, days: int = DEFAULT_RETENTION_DAYS
) -> int:
    """Delete sync_runs with started_at older than `days`. Returns rows deleted."""
    cutoff = _utcnow() - timedelta(days=max(1, int(days)))
    q = db.query(SyncRun).filter(SyncRun.started_at < cutoff)
    # SQLite/SQLAlchemy: count then delete
    rows = q.all()
    n = len(rows)
    for row in rows:
        db.delete(row)
    if n:
        db.flush()
    return n
