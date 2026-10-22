# tests/test_sync_runs.py
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class SyncRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.db import Base
        from app.models import User

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()
        self.user = User(feishu_open_id="ou_test", display_name="测试用户")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_record_and_list_within_window(self) -> None:
        from app.sync_runs import list_recent_runs, record_sync_run

        now = datetime.now(timezone.utc)
        row = record_sync_run(
            self.db,
            self.user.id,
            trigger="manual",
            status="ok",
            message="create=1 update=0",
            created=1,
            updated=0,
            deleted=0,
            started_at=now,
            finished_at=now,
        )
        self.db.commit()
        self.assertIsNotNone(row.id)
        runs = list_recent_runs(self.db, self.user.id, days=7)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].trigger, "manual")
        self.assertEqual(runs[0].status, "ok")
        self.assertEqual(runs[0].created_count, 1)
        self.assertIn("create=1", runs[0].message or "")

    def test_list_excludes_older_than_7_days(self) -> None:
        from app.sync_runs import list_recent_runs, record_sync_run

        now = datetime.now(timezone.utc)
        record_sync_run(
            self.db,
            self.user.id,
            trigger="poll",
            status="ok",
            message="recent",
            started_at=now - timedelta(days=1),
            finished_at=now - timedelta(days=1),
        )
        record_sync_run(
            self.db,
            self.user.id,
            trigger="poll",
            status="ok",
            message="old",
            started_at=now - timedelta(days=8),
            finished_at=now - timedelta(days=8),
        )
        self.db.commit()
        runs = list_recent_runs(self.db, self.user.id, days=7)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].message, "recent")

    def test_purge_old_runs(self) -> None:
        from app.sync_runs import list_recent_runs, purge_old_runs, record_sync_run

        now = datetime.now(timezone.utc)
        record_sync_run(
            self.db,
            self.user.id,
            trigger="push",
            status="error",
            message="keep",
            started_at=now - timedelta(days=2),
            finished_at=now - timedelta(days=2),
        )
        record_sync_run(
            self.db,
            self.user.id,
            trigger="push",
            status="error",
            message="purge-me",
            started_at=now - timedelta(days=10),
            finished_at=now - timedelta(days=10),
        )
        self.db.commit()
        deleted = purge_old_runs(self.db, days=7)
        self.db.commit()
        self.assertEqual(deleted, 1)
        runs = list_recent_runs(self.db, self.user.id, days=30)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].message, "keep")

    def test_record_rejects_invalid_trigger(self) -> None:
        from app.sync_runs import record_sync_run

        with self.assertRaises(ValueError):
            record_sync_run(
                self.db,
                self.user.id,
                trigger="webhook",
                status="ok",
                message="x",
            )

    def test_sync_user_records_run_and_skips_dry_run(self) -> None:
        from app.models import SyncRun
        from app.sync_runs import list_recent_runs
        from app.sync_service import sync_user

        # Missing tokens → error path still records (unless dry_run)
        result = sync_user(self.db, self.user, dry_run=False, trigger="poll")
        self.db.commit()
        self.assertEqual(result.errors, 1)
        runs = list_recent_runs(self.db, self.user.id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].trigger, "poll")
        self.assertEqual(runs[0].status, "error")

        before = self.db.query(SyncRun).count()
        sync_user(self.db, self.user, dry_run=True, trigger="manual")
        self.db.commit()
        self.assertEqual(self.db.query(SyncRun).count(), before)


if __name__ == "__main__":
    unittest.main()
