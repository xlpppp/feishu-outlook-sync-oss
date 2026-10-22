"""APScheduler background sync + daily DB backup + Graph subscription renewal."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .backup import run_backup
from .config import get_settings
from .db import session_scope
from .sync_service import sync_all_enabled

log = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def _job() -> None:
    log.info("定时同步开始…")
    try:
        with session_scope() as db:
            n = sync_all_enabled(db)
        log.info("定时同步结束，处理 %d 个用户", n)
    except Exception:
        log.exception("定时同步异常")


def _backup_job() -> None:
    log.info("定时备份开始…")
    try:
        path = run_backup()
        if path:
            log.info("定时备份完成: %s", path)
    except Exception:
        log.exception("定时备份异常")


def _renew_graph_subscriptions_job() -> None:
    log.info("Graph 订阅续期检查开始…")
    try:
        from .push_subscriptions import renew_expiring_graph_subscriptions

        with session_scope() as db:
            n = renew_expiring_graph_subscriptions(db)
        log.info("Graph 订阅续期检查结束，处理 %d 个", n)
    except Exception:
        log.exception("Graph 订阅续期异常")


def _purge_sync_runs_job() -> None:
    log.info("清理过期 sync_runs…")
    try:
        from .sync_runs import purge_old_runs

        with session_scope() as db:
            n = purge_old_runs(db, days=7)
        log.info("清理过期 sync_runs 结束，删除 %d 条", n)
    except Exception:
        log.exception("清理 sync_runs 异常")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    sched = BackgroundScheduler(timezone=settings.timezone)
    minutes = max(1, settings.sync_interval_minutes)
    sched.add_job(
        _job,
        "interval",
        minutes=minutes,
        id="sync_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.backup_enabled:
        hour = max(0, min(23, settings.backup_hour))
        minute = max(0, min(59, settings.backup_minute))
        sched.add_job(
            _backup_job,
            CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
            id="daily_backup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info(
            "每日备份已启用：%02d:%02d（%s）→ %s，保留 %d 份",
            hour,
            minute,
            settings.timezone,
            settings.backup_dir,
            settings.backup_keep_days,
        )
    if settings.graph_push_active():
        # Check every 6 hours; renew when within GRAPH_SUBSCRIPTION_RENEW_HOURS of expiry
        sched.add_job(
            _renew_graph_subscriptions_job,
            "interval",
            hours=6,
            id="renew_graph_subscriptions",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("Graph 订阅自动续期已启用（每 6 小时检查）")
    # Daily retention for sync_runs (also purged on startup)
    sched.add_job(
        _purge_sync_runs_job,
        CronTrigger(hour=3, minute=15, timezone=settings.timezone),
        id="purge_sync_runs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info(
        "APScheduler 已启动，每 %d 分钟同步一次（push=%s）",
        minutes,
        "on" if settings.push_sync_enabled else "off",
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("APScheduler 已停止")
