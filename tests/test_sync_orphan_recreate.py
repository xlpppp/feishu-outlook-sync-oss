"""f2o/o2f: recreate when hash matches but target event is gone."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models import ORIGIN_F2O, ORIGIN_O2F  # noqa: E402
from app.sync_service import (  # noqa: E402
    _sync_feishu_to_outlook,
    _sync_outlook_to_feishu,
)

TZ = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 10, 13, tzinfo=TZ)
END = datetime(2026, 12, 19, 23, 59, 59, tzinfo=TZ)


def _settings(**overrides):
    base = SimpleNamespace(
        timezone="Asia/Shanghai",
        outlook_calendar_name="Feishu Sync",
        feishu_sync_calendar_name="Outlook Sync",
        skip_subscribed_calendars=True,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


class FakeMapping:
    def __init__(
        self,
        *,
        feishu_event_id: str,
        outlook_event_id: str,
        content_hash: str,
        direction: str,
        user_id: int = 1,
    ):
        self.user_id = user_id
        self.feishu_event_id = feishu_event_id
        self.outlook_event_id = outlook_event_id
        self.content_hash = content_hash
        self.direction = direction
        self.updated_at = None


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, mappings):
        self._mappings = list(mappings)
        self.added = []
        self.deleted = []

    def query(self, model):  # noqa: ANN001
        return FakeQuery(self._mappings)

    def add(self, row):  # noqa: ANN001
        self.added.append(row)
        self._mappings.append(row)

    def delete(self, row):  # noqa: ANN001
        self.deleted.append(row)
        if row in self._mappings:
            self._mappings.remove(row)

    def flush(self):
        pass


class F2OOrphanRecreateTests(unittest.TestCase):
    def test_hash_match_but_outlook_missing_recreates(self) -> None:
        feishu_ev = {
            "event_id": "fs-friday",
            "summary": "周五例会",
            "start_time": {
                "timestamp": str(int(datetime(2026, 10, 17, 10, tzinfo=TZ).timestamp()))
            },
            "end_time": {
                "timestamp": str(int(datetime(2026, 10, 17, 11, tzinfo=TZ).timestamp()))
            },
        }
        # Same hash as util would compute — use the real hasher
        from app.util import event_content_hash

        h = event_content_hash(feishu_ev, "Asia/Shanghai")
        mapped = FakeMapping(
            feishu_event_id="fs-friday",
            outlook_event_id="gone-outlook-id",
            content_hash=h,
            direction=ORIGIN_F2O,
        )
        db = FakeSession([mapped])
        user = SimpleNamespace(
            id=1,
            outlook_calendar_name="Feishu Sync",
            outlook_calendar_id=None,
        )

        with (
            patch("app.sync_service.get_settings", return_value=_settings()),
            patch(
                "app.sync_service.feishu_api.pull_primary_events",
                return_value=[feishu_ev],
            ),
            patch(
                "app.sync_service.graph_api.ensure_calendar",
                return_value={"id": "cal-target"},
            ),
            patch(
                "app.sync_service.graph_api.list_events",
                return_value=[],  # orphan: mapped id not present
            ) as list_target,
            patch(
                "app.sync_service.graph_api.create_event",
                return_value={"id": "new-outlook-id"},
            ) as create_ev,
            patch("app.sync_service.graph_api.update_event") as update_ev,
            patch("app.sync_service.graph_api.delete_event") as delete_ev,
        ):
            result = _sync_feishu_to_outlook(
                db,
                user,
                feishu_token="ft",
                ms_token="mt",
                start=START,
                end=END,
                dry_run=False,
            )

        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.errors, 0)
        create_ev.assert_called_once()
        update_ev.assert_not_called()
        delete_ev.assert_not_called()
        list_target.assert_called_once()
        self.assertEqual(mapped.outlook_event_id, "new-outlook-id")
        self.assertEqual(mapped.content_hash, h)

    def test_hash_match_and_present_skips(self) -> None:
        feishu_ev = {
            "event_id": "fs-ok",
            "summary": "仍在",
            "start_time": {
                "timestamp": str(int(datetime(2026, 10, 17, 10, tzinfo=TZ).timestamp()))
            },
            "end_time": {
                "timestamp": str(int(datetime(2026, 10, 17, 11, tzinfo=TZ).timestamp()))
            },
        }
        from app.util import event_content_hash

        h = event_content_hash(feishu_ev, "Asia/Shanghai")
        mapped = FakeMapping(
            feishu_event_id="fs-ok",
            outlook_event_id="still-there",
            content_hash=h,
            direction=ORIGIN_F2O,
        )
        db = FakeSession([mapped])
        user = SimpleNamespace(
            id=1,
            outlook_calendar_name="Feishu Sync",
            outlook_calendar_id="cal-target",
        )

        with (
            patch("app.sync_service.get_settings", return_value=_settings()),
            patch(
                "app.sync_service.feishu_api.pull_primary_events",
                return_value=[feishu_ev],
            ),
            patch(
                "app.sync_service.graph_api.ensure_calendar",
                return_value={"id": "cal-target"},
            ),
            patch(
                "app.sync_service.graph_api.list_events",
                return_value=[{"id": "still-there", "subject": "仍在"}],
            ),
            patch("app.sync_service.graph_api.create_event") as create_ev,
            patch("app.sync_service.graph_api.update_event") as update_ev,
        ):
            result = _sync_feishu_to_outlook(
                db,
                user,
                feishu_token="ft",
                ms_token="mt",
                start=START,
                end=END,
                dry_run=False,
            )

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 1)
        create_ev.assert_not_called()
        update_ev.assert_not_called()


class O2FOrphanRecreateTests(unittest.TestCase):
    def test_hash_match_but_feishu_missing_recreates(self) -> None:
        outlook_ev = {
            "id": "ol-1",
            "subject": "从Outlook",
            "start": {
                "dateTime": "2026-10-17T10:00:00",
                "timeZone": "Asia/Shanghai",
            },
            "end": {
                "dateTime": "2026-10-17T11:00:00",
                "timeZone": "Asia/Shanghai",
            },
            "location": {},
            "body": {},
            "isAllDay": False,
        }
        from app.util import outlook_event_content_hash

        h = outlook_event_content_hash(outlook_ev, "Asia/Shanghai")
        mapped = FakeMapping(
            feishu_event_id="gone-feishu-id",
            outlook_event_id="ol-1",
            content_hash=h,
            direction=ORIGIN_O2F,
        )
        db = FakeSession([mapped])
        user = SimpleNamespace(
            id=1,
            outlook_calendar_name="Feishu Sync",
            outlook_calendar_id=None,
        )

        with (
            patch("app.sync_service.get_settings", return_value=_settings()),
            patch(
                "app.sync_service.graph_api.get_default_calendar",
                return_value={"id": "cal-default", "name": "Calendar"},
            ),
            patch(
                "app.sync_service.graph_api.list_events",
                return_value=[outlook_ev],
            ),
            patch(
                "app.sync_service.feishu_api.ensure_named_calendar",
                return_value={"calendar_id": "fcal-target"},
            ),
            patch(
                "app.sync_service.feishu_api.list_events",
                return_value=[],  # orphan on Feishu target
            ),
            patch(
                "app.sync_service.feishu_api.create_event",
                return_value={"event_id": "new-feishu-id"},
            ) as create_ev,
            patch("app.sync_service.feishu_api.patch_event") as patch_ev,
            patch("app.sync_service.feishu_api.delete_event") as delete_ev,
        ):
            result = _sync_outlook_to_feishu(
                db,
                user,
                feishu_token="ft",
                ms_token="mt",
                start=START,
                end=END,
                dry_run=False,
            )

        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.errors, 0)
        create_ev.assert_called_once()
        patch_ev.assert_not_called()
        delete_ev.assert_not_called()
        self.assertEqual(mapped.feishu_event_id, "new-feishu-id")


if __name__ == "__main__":
    unittest.main()
