"""Daily SQLite backup into BACKUP_DIR (default /data/backups)."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import get_settings

log = logging.getLogger("backup")

_BACKUP_NAME = re.compile(r"^sync-\d{8}(?:-\d{6})?\.db$")


def sqlite_path_from_url(database_url: str) -> Path | None:
    """Parse sqlite:///... or sqlite:////absolute into a Path."""
    url = (database_url or "").strip()
    if not url.startswith("sqlite:"):
        return None
    # sqlite:////data/sync.db  -> /data/sync.db
    # sqlite:///./data/sync.db -> relative
    raw = url[len("sqlite:") :]
    if raw.startswith("////"):
        return Path("/" + raw.lstrip("/"))
    if raw.startswith("///"):
        rest = raw[3:]
        return Path(rest if rest.startswith("/") else rest)
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    if path:
        return Path(path)
    return None


def run_backup() -> Path | None:
    settings = get_settings()
    if not settings.backup_enabled:
        log.info("备份已关闭（BACKUP_ENABLED=false）")
        return None

    db_path = sqlite_path_from_url(settings.database_url)
    if db_path is None:
        log.warning("当前 DATABASE_URL 不是 sqlite，跳过备份: %s", settings.database_url)
        return None
    if not db_path.is_file():
        log.warning("数据库文件不存在，跳过备份: %s", db_path)
        return None

    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    dest = backup_dir / f"sync-{stamp}.db"

    # Online-safe copy via SQLite backup API
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
            dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst.close()
    finally:
        src.close()

    size = dest.stat().st_size
    log.info("数据库已备份 → %s (%d bytes)", dest, size)
    _prune_old(backup_dir, settings.backup_keep_days)
    return dest


def _prune_old(backup_dir: Path, keep_days: int) -> None:
    keep = max(1, int(keep_days))
    files = sorted(
        [p for p in backup_dir.iterdir() if p.is_file() and _BACKUP_NAME.match(p.name)],
        key=lambda p: p.name,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
            log.info("已删除过期备份: %s", old.name)
        except OSError:
            log.exception("删除备份失败: %s", old)
