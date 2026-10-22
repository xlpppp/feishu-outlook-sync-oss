"""Debounce + per-user lock for push-triggered sync_user calls."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

log = logging.getLogger("push_debounce")

# Default coalesce window (seconds); overridden by Settings.push_debounce_seconds
DEFAULT_DEBOUNCE_SECONDS = 20

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()
_pending_reasons: dict[int, str] = {}


def _user_lock(user_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _locks[user_id] = lock
        return lock


def debounce_delay_seconds(configured: Optional[int] = None) -> int:
    """Clamp debounce to 15–30s as design target; allow explicit config in that band."""
    if configured is None:
        return DEFAULT_DEBOUNCE_SECONDS
    return max(15, min(30, int(configured)))


def schedule_user_sync(
    user_id: int,
    *,
    reason: str,
    delay_seconds: Optional[int] = None,
    scheduler=None,
) -> bool:
    """
    Coalesce multiple pushes for the same user into one delayed sync_user.
    Uses APScheduler date job id push_sync_{user_id} with replace_existing=True
    (max_instances=1 style). Returns True if a job was scheduled/rescheduled.
    """
    from .config import get_settings
    from .scheduler import get_scheduler

    settings = get_settings()
    delay = debounce_delay_seconds(
        delay_seconds if delay_seconds is not None else settings.push_debounce_seconds
    )
    sched = scheduler if scheduler is not None else get_scheduler()
    if sched is None:
        log.warning(
            "push debounce: scheduler 未启动，立即同步 user=%s reason=%s",
            user_id,
            reason,
        )
        run_debounced_user_sync(user_id, reason=reason)
        return True

    _pending_reasons[user_id] = reason
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    job_id = f"push_sync_{user_id}"
    sched.add_job(
        run_debounced_user_sync,
        "date",
        run_date=run_at,
        id=job_id,
        replace_existing=True,
        args=[user_id],
        kwargs={"reason": reason},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    log.info(
        "push 已入队 user=%s reason=%s debounce=%ss",
        user_id,
        reason,
        delay,
    )
    return True


def run_debounced_user_sync(user_id: int, reason: str = "push") -> None:
    """Execute sync_user under a per-user lock (skip if already running)."""
    from .db import session_scope
    from .models import User
    from .sync_service import sync_user

    reason = _pending_reasons.pop(user_id, None) or reason
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        log.info(
            "push 同步跳过（用户锁占用）user=%s reason=%s",
            user_id,
            reason,
        )
        # Re-schedule once so we don't drop the notification entirely
        schedule_user_sync(user_id, reason=reason)
        return

    try:
        log.info("push 触发同步开始 user=%s reason=%s", user_id, reason)
        with session_scope() as db:
            user = db.get(User, user_id)
            if user is None:
                log.warning("push 同步：用户不存在 user=%s", user_id)
                return
            if not user.sync_enabled:
                log.info("push 同步跳过（已关闭自动同步）user=%s", user_id)
                return
            result = sync_user(db, user, dry_run=False, trigger="push")
            log.info(
                "push 触发同步结束 user=%s reason=%s status=%s msg=%s",
                user_id,
                reason,
                user.last_sync_status,
                (result.message or "")[:200],
            )
    except Exception:
        log.exception("push 同步异常 user=%s reason=%s", user_id, reason)
    finally:
        lock.release()


# Test helper: reset in-memory state
def _reset_for_tests() -> None:
    with _locks_guard:
        _locks.clear()
    _pending_reasons.clear()
