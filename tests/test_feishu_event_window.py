"""Unit tests for Feishu list_events instance_view chunking / window helpers."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.feishu_api import (  # noqa: E402
    FEISHU_ERR_INSTANCE_VIEW_TOO_MANY,
    INSTANCE_VIEW_MAX_SPAN,
    event_overlaps_window,
    iter_instance_view_chunks,
    list_events,
    merge_events_by_id,
    parse_feishu_bound_to_dt,
)


TZ = ZoneInfo("Asia/Shanghai")


class ParseBoundTests(unittest.TestCase):
    def test_timestamp(self) -> None:
        # 2020-10-12 20:00:00 +08 → 1602504000
        dt = parse_feishu_bound_to_dt(
            {"timestamp": "1602504000", "timezone": "Asia/Shanghai"}
        )
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(int(dt.timestamp()), 1602504000)

    def test_date(self) -> None:
        dt = parse_feishu_bound_to_dt(
            {"date": "2026-10-25", "timezone": "Asia/Shanghai"}
        )
        self.assertEqual(dt, datetime(2026, 10, 25, tzinfo=TZ))

    def test_empty(self) -> None:
        self.assertIsNone(parse_feishu_bound_to_dt(None))
        self.assertIsNone(parse_feishu_bound_to_dt({}))


class OverlapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 10, 1, tzinfo=TZ)
        self.end = datetime(2026, 10, 31, 23, 59, 59, tzinfo=TZ)

    def test_inside_window(self) -> None:
        ev = {
            "start_time": {"timestamp": str(int(datetime(2026, 10, 15, 10, tzinfo=TZ).timestamp()))},
            "end_time": {"timestamp": str(int(datetime(2026, 10, 15, 11, tzinfo=TZ).timestamp()))},
        }
        self.assertTrue(event_overlaps_window(ev, self.start, self.end))

    def test_before_window_dropped(self) -> None:
        ev = {
            "start_time": {"timestamp": str(int(datetime(2026, 9, 1, 10, tzinfo=TZ).timestamp()))},
            "end_time": {"timestamp": str(int(datetime(2026, 9, 1, 11, tzinfo=TZ).timestamp()))},
        }
        self.assertFalse(event_overlaps_window(ev, self.start, self.end))

    def test_after_window_dropped(self) -> None:
        ev = {
            "start_time": {"timestamp": str(int(datetime(2026, 11, 5, 10, tzinfo=TZ).timestamp()))},
            "end_time": {"timestamp": str(int(datetime(2026, 11, 5, 11, tzinfo=TZ).timestamp()))},
        }
        self.assertFalse(event_overlaps_window(ev, self.start, self.end))

    def test_all_day_date(self) -> None:
        ev = {
            "start_time": {"date": "2026-10-20", "timezone": "Asia/Shanghai"},
            "end_time": {"date": "2026-10-20", "timezone": "Asia/Shanghai"},
        }
        self.assertTrue(event_overlaps_window(ev, self.start, self.end))

    def test_missing_times_kept(self) -> None:
        self.assertTrue(event_overlaps_window({"summary": "x"}, self.start, self.end))


class ChunkAndDedupeTests(unittest.TestCase):
    def test_sync_window_split_under_40_days(self) -> None:
        """~67-day sync window → adjacent chunks each ≤ 39 days."""
        start = datetime(2026, 9, 14, 0, 0, 0, tzinfo=TZ)
        end = datetime(2026, 11, 20, 23, 59, 59, tzinfo=TZ)  # ~67 days
        chunks = iter_instance_view_chunks(start, end)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0][0], start)
        self.assertEqual(chunks[-1][1], end)
        for i, (a, b) in enumerate(chunks):
            self.assertLessEqual(b - a, INSTANCE_VIEW_MAX_SPAN)
            self.assertLess(b - a, timedelta(days=40))
            if i > 0:
                # Shared boundary instant (overlap for safety)
                self.assertEqual(a, chunks[i - 1][1])

    def test_short_window_one_chunk(self) -> None:
        start = datetime(2026, 10, 1, tzinfo=TZ)
        end = datetime(2026, 10, 20, tzinfo=TZ)
        chunks = iter_instance_view_chunks(start, end)
        self.assertEqual(chunks, [(start, end)])

    def test_merge_dedupes_by_event_id(self) -> None:
        a = {"event_id": "uid_100", "summary": "first"}
        b = {"event_id": "uid_100", "summary": "second"}
        c = {"event_id": "uid_200", "summary": "other"}
        merged = merge_events_by_id([a, c, b])
        by_id = {e["event_id"]: e for e in merged}
        self.assertEqual(set(by_id), {"uid_100", "uid_200"})
        self.assertEqual(by_id["uid_100"]["summary"], "second")


class ListEventsInstanceViewTests(unittest.TestCase):
    def test_chunks_calls_instance_view_and_dedupes(self) -> None:
        """Wide window → multiple instance_view GETs; boundary dupes collapsed."""
        window_start = datetime(2026, 9, 14, 0, 0, 0, tzinfo=TZ)
        window_end = datetime(2026, 11, 20, 23, 59, 59, tzinfo=TZ)
        chunks = iter_instance_view_chunks(window_start, window_end)
        self.assertGreaterEqual(len(chunks), 2)

        def _ts(dt: datetime) -> str:
            return str(int(dt.timestamp()))

        # Shared boundary instance appears in every overlapping chunk response
        boundary = chunks[0][1]
        shared = {
            "event_id": "series_111",
            "status": "confirmed",
            "summary": "weekly",
            "start_time": {"timestamp": _ts(boundary), "timezone": "Asia/Shanghai"},
            "end_time": {
                "timestamp": _ts(boundary + timedelta(hours=1)),
                "timezone": "Asia/Shanghai",
            },
        }
        wed1 = {
            "event_id": "series_100",
            "status": "confirmed",
            "summary": "weekly",
            "start_time": {
                "timestamp": _ts(datetime(2026, 9, 16, 10, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
            "end_time": {
                "timestamp": _ts(datetime(2026, 9, 16, 11, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
        }
        wed2 = {
            "event_id": "series_222",
            "status": "confirmed",
            "summary": "weekly",
            "start_time": {
                "timestamp": _ts(datetime(2026, 11, 4, 10, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
            "end_time": {
                "timestamp": _ts(datetime(2026, 11, 4, 11, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
        }
        cancelled = {
            "event_id": "series_999",
            "status": "cancelled",
            "start_time": {
                "timestamp": _ts(datetime(2026, 10, 7, 10, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
            "end_time": {
                "timestamp": _ts(datetime(2026, 10, 7, 11, tzinfo=TZ)),
                "timezone": "Asia/Shanghai",
            },
        }

        # First chunk: wed1 + shared + cancelled; later chunks: shared + wed2
        per_chunk_items = []
        for i, _ in enumerate(chunks):
            if i == 0:
                per_chunk_items.append([wed1, shared, cancelled])
            else:
                per_chunk_items.append([shared, wed2])

        call_i = {"n": 0}
        seen_urls: list[str] = []
        seen_params: list[dict] = []

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        def _json_side_effect() -> dict:
            idx = call_i["n"] - 1
            return {"code": 0, "data": {"items": per_chunk_items[idx]}}

        mock_resp.json.side_effect = _json_side_effect

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False

        def _get(url: str, headers=None, params=None):  # noqa: ANN001
            call_i["n"] += 1
            seen_urls.append(url)
            seen_params.append(dict(params or {}))
            return mock_resp

        mock_client.get.side_effect = _get

        with patch("app.feishu_api.httpx.Client", return_value=mock_client):
            events = list_events(
                "tok",
                "cal@feishu.cn",
                start=window_start,
                end=window_end,
            )

        self.assertEqual(len(seen_params), len(chunks))
        for url in seen_urls:
            self.assertIn("/events/instance_view", url)
            self.assertNotIn("/events?", url)

        for i, (c_start, c_end) in enumerate(chunks):
            self.assertEqual(
                seen_params[i]["start_time"], str(int(c_start.timestamp()))
            )
            self.assertEqual(
                seen_params[i]["end_time"], str(int(c_end.timestamp()))
            )

        ids = {e["event_id"] for e in events}
        self.assertEqual(ids, {"series_100", "series_111", "series_222"})
        self.assertNotIn("series_999", ids)

    def test_too_many_instances_bisects(self) -> None:
        window_start = datetime(2026, 10, 1, tzinfo=TZ)
        window_end = datetime(2026, 10, 20, tzinfo=TZ)

        calls: list[tuple[str, str]] = []

        def _ok_items(start_ts: str, end_ts: str) -> dict:
            return {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "event_id": f"id_{start_ts}",
                            "status": "confirmed",
                            "start_time": {
                                "timestamp": start_ts,
                                "timezone": "Asia/Shanghai",
                            },
                            "end_time": {
                                "timestamp": str(int(start_ts) + 3600),
                                "timezone": "Asia/Shanghai",
                            },
                        }
                    ]
                },
            }

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False

        def _get(_url: str, headers=None, params=None):  # noqa: ANN001
            st = str((params or {})["start_time"])
            et = str((params or {})["end_time"])
            calls.append((st, et))
            resp = MagicMock()
            resp.status_code = 200
            # First call (full window) → too many; subsequent halves succeed
            if len(calls) == 1:
                resp.json.return_value = {
                    "code": FEISHU_ERR_INSTANCE_VIEW_TOO_MANY,
                    "msg": "too many",
                }
            else:
                resp.json.return_value = _ok_items(st, et)
            return resp

        mock_client.get.side_effect = _get

        with patch("app.feishu_api.httpx.Client", return_value=mock_client):
            events = list_events(
                "tok",
                "cal@feishu.cn",
                start=window_start,
                end=window_end,
            )

        self.assertGreaterEqual(len(calls), 3)  # 1 fail + 2 halves
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["event_id"].startswith("id_") for e in events))


if __name__ == "__main__":
    unittest.main()
