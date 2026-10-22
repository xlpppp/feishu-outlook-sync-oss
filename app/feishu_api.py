"""Feishu calendar Open API (user_access_token)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("feishu_api")

API_ROOT = "https://open.feishu.cn/open-apis"

# instance_view: start_time/end_time span must be < 40 days; instance count < 1000.
# Docs: https://open.feishu.cn/document/calendar-v4/calendar-event/instance_view
INSTANCE_VIEW_MAX_SPAN = timedelta(days=39)
# When Feishu returns too-many / range errors, bisect; stop below this floor.
INSTANCE_VIEW_MIN_SPLIT = timedelta(hours=2)
FEISHU_ERR_INSTANCE_VIEW_RANGE = 193103
FEISHU_ERR_INSTANCE_VIEW_TOO_MANY = 193104
INSTANCE_VIEW_MAX_DEPTH = 10


class FeishuApiError(RuntimeError):
    def __init__(self, message: str, *, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _check(data: dict, action: str) -> dict:
    if not isinstance(data, dict):
        raise FeishuApiError(f"{action}: 非对象响应")
    code = data.get("code")
    if code not in (0, None):
        raise FeishuApiError(
            f"{action} 失败: code={code} msg={data.get('msg')}",
            code=int(code) if code is not None else None,
        )
    return data.get("data") if "data" in data else data


def list_calendars(user_access_token: str) -> List[dict]:
    """GET /calendar/v4/calendars (paginate)."""
    results: List[dict] = []
    page_token: Optional[str] = None
    with httpx.Client(timeout=60.0) as client:
        while True:
            params: Dict[str, Any] = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            resp = client.get(
                f"{API_ROOT}/calendar/v4/calendars",
                headers=_headers(user_access_token),
                params=params,
            )
            try:
                body = resp.json()
            except Exception as e:
                raise FeishuApiError(
                    f"list calendars 非 JSON: {resp.status_code}"
                ) from e
            data = _check(body, "list calendars")
            cal_list = (data or {}).get("calendar_list") or []
            results.extend([c for c in cal_list if isinstance(c, dict)])
            page_token = (data or {}).get("page_token")
            if not page_token or not (data or {}).get("has_more"):
                break
    log.info("飞书日历: %d 个", len(results))
    return results


def calendar_summary(cal: dict) -> str:
    return (cal.get("summary") or cal.get("summary_alias") or "").strip()


# Feishu calendar list API: https://open.feishu.cn/document/server-docs/calendar-v4/calendar/introduction
# type: primary | shared | google | resource | exchange | unknown
# role: owner | writer | reader (订阅者) | free_busy_reader (访客) | unknown
# Subscribed (订阅) calendars are typically type=shared with role=reader — there is no type=subscribed.
SUBSCRIBED_ROLES = frozenset({"reader", "free_busy_reader"})


def is_subscribed_calendar(cal: dict) -> bool:
    """True when current identity is only a subscriber/guest on this calendar."""
    if not isinstance(cal, dict):
        return False
    role = (cal.get("role") or "").strip().lower()
    return role in SUBSCRIBED_ROLES


def filter_calendars_for_sync(
    calendars: List[dict],
    *,
    skip_subscribed: bool = True,
) -> List[dict]:
    """Drop subscribed calendars when skip_subscribed is True; keep order."""
    if not skip_subscribed:
        return [c for c in calendars if isinstance(c, dict)]
    out: List[dict] = []
    skipped = 0
    for c in calendars:
        if not isinstance(c, dict):
            continue
        if is_subscribed_calendar(c):
            skipped += 1
            name = calendar_summary(c) or (c.get("calendar_id") or c.get("id") or "?")
            log.info(
                "跳过订阅日历: %s (type=%s role=%s)",
                name,
                c.get("type"),
                c.get("role"),
            )
            continue
        out.append(c)
    if skipped:
        log.info("已跳过 %d 个订阅/访客日历（SKIP_SUBSCRIBED_CALENDARS）", skipped)
    return out


def primary_calendar_id(
    calendars: List[dict],
    *,
    skip_subscribed: bool = True,
) -> Optional[str]:
    """Prefer type=primary; never fall back onto a subscribed calendar when skipping."""
    cals = filter_calendars_for_sync(calendars, skip_subscribed=skip_subscribed)
    for c in cals:
        if (c.get("type") or "").lower() == "primary":
            return c.get("calendar_id") or c.get("id")
    if cals:
        return cals[0].get("calendar_id") or cals[0].get("id")
    return None


def ensure_named_calendar(user_access_token: str, name: str) -> dict:
    """
    Find calendar by summary/name; if missing create via
    POST /calendar/v4/calendars with summary, description, permissions=private.
    Returns calendar dict including calendar_id.
    """
    name = (name or "").strip()
    if not name:
        raise FeishuApiError("日历名称不能为空")

    for c in list_calendars(user_access_token):
        if calendar_summary(c) == name:
            log.info("使用已有飞书日历: %s", name)
            return c

    log.info("创建飞书日历: %s", name)
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{API_ROOT}/calendar/v4/calendars",
            headers=_headers(user_access_token),
            json={
                "summary": name,
                "description": "由飞书↔Outlook 同步服务自动创建；请勿手动改本日历日程。",
                "permissions": "private",
            },
        )
        try:
            body = resp.json()
        except Exception as e:
            raise FeishuApiError(
                f"create calendar 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        data = _check(body, "create calendar")
        cal = (data or {}).get("calendar") or data or {}
        if not isinstance(cal, dict) or not (cal.get("calendar_id") or cal.get("id")):
            raise FeishuApiError(f"create calendar 响应缺少 calendar_id: {body}")
        return cal


def _zoneinfo(tz_name: Optional[str], default_tz: str = "Asia/Shanghai") -> ZoneInfo:
    name = (tz_name or default_tz or "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def parse_feishu_bound_to_dt(
    time_obj: Optional[dict],
    *,
    default_tz: str = "Asia/Shanghai",
) -> Optional[datetime]:
    """Parse Feishu time_info (`date` or unix `timestamp`) to an aware datetime."""
    if not time_obj or not isinstance(time_obj, dict):
        return None

    tz = _zoneinfo(time_obj.get("timezone"), default_tz)

    if time_obj.get("date"):
        d = str(time_obj["date"])[:10]
        try:
            return datetime.fromisoformat(d).replace(tzinfo=tz)
        except ValueError:
            return None

    ts = time_obj.get("timestamp")
    if ts is not None and str(ts).strip() != "":
        try:
            # Feishu timestamps are unix seconds (absolute); attach UTC then compare
            return datetime.fromtimestamp(int(str(ts)), tz=ZoneInfo("UTC"))
        except (ValueError, OSError, OverflowError):
            return None

    dt_str = time_obj.get("datetime")
    if not dt_str:
        return None
    s = str(dt_str).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt


def event_overlaps_window(
    event: dict,
    start: datetime,
    end: datetime,
    *,
    default_tz: str = "Asia/Shanghai",
) -> bool:
    """
    True when event time range intersects [start, end] (inclusive bounds).

    If either bound cannot be parsed, keep the event (avoid silent drops;
    sync mapping will fail later if times are truly missing).
    """
    if not isinstance(event, dict):
        return False
    ev_start = parse_feishu_bound_to_dt(
        event.get("start_time"), default_tz=default_tz
    )
    ev_end = parse_feishu_bound_to_dt(
        event.get("end_time"), default_tz=default_tz
    )
    if ev_start is None or ev_end is None:
        return True
    # All-day single-day often has identical date midnights — treat as one day
    if ev_end < ev_start:
        ev_end = ev_start
    if ev_end == ev_start:
        ev_end = ev_start + timedelta(days=1)
    return ev_start <= end and ev_end >= start


def iter_instance_view_chunks(
    start: datetime,
    end: datetime,
    *,
    max_span: timedelta = INSTANCE_VIEW_MAX_SPAN,
) -> List[Tuple[datetime, datetime]]:
    """
    Split ``[start, end]`` into contiguous slices each spanning at most
    ``max_span`` (Feishu instance_view requires span < 40 days).

    Adjacent chunks share the boundary instant so nothing is dropped at the
    cut; callers must dedupe by ``event_id``.
    """
    if end < start:
        raise ValueError("iter_instance_view_chunks: end must be >= start")
    if max_span <= timedelta(0):
        raise ValueError("iter_instance_view_chunks: max_span must be positive")

    chunks: List[Tuple[datetime, datetime]] = []
    cursor = start
    while True:
        chunk_end = min(cursor + max_span, end)
        chunks.append((cursor, chunk_end))
        if chunk_end >= end:
            break
        cursor = chunk_end
    return chunks


def merge_events_by_id(events: List[dict]) -> List[dict]:
    """Dedupe by event_id (last write wins); drop items without event_id."""
    by_id: Dict[str, dict] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("event_id")
        if not eid:
            continue
        by_id[str(eid)] = ev
    return list(by_id.values())


def _is_cancelled_event(ev: dict) -> bool:
    return (ev.get("status") or "").lower() in ("cancelled", "canceled")


def _fetch_instance_view_once(
    client: httpx.Client,
    user_access_token: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
) -> List[dict]:
    """Single instance_view GET for one chunk (no auto-split)."""
    encoded_cid = quote(calendar_id, safe="")
    url = f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events/instance_view"
    params = {
        "start_time": str(int(start.timestamp())),
        "end_time": str(int(end.timestamp())),
    }
    resp = client.get(url, headers=_headers(user_access_token), params=params)
    try:
        body = resp.json()
    except Exception as e:
        raise FeishuApiError(
            f"instance_view 非 JSON: {resp.status_code} {resp.text[:200]}"
        ) from e
    data = _check(body, "instance_view")
    items = (data or {}).get("items") or []
    out: List[dict] = []
    for ev in items:
        if not isinstance(ev, dict):
            continue
        if _is_cancelled_event(ev):
            continue
        out.append(ev)
    return out


def _fetch_instance_view_range(
    client: httpx.Client,
    user_access_token: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
    *,
    depth: int = 0,
) -> List[dict]:
    """
    Fetch instance_view for ``[start, end]``, bisecting on Feishu 193103
    (range) / 193104 (too many instances) until the window is small enough.
    """
    if end < start:
        return []
    if depth > INSTANCE_VIEW_MAX_DEPTH:
        raise FeishuApiError(
            f"instance_view 分片过深（>{INSTANCE_VIEW_MAX_DEPTH}）: "
            f"{start.isoformat()} .. {end.isoformat()}"
        )

    span = end - start
    if span > INSTANCE_VIEW_MAX_SPAN:
        mid = start + span / 2
        left = _fetch_instance_view_range(
            client,
            user_access_token,
            calendar_id,
            start,
            mid,
            depth=depth + 1,
        )
        right = _fetch_instance_view_range(
            client,
            user_access_token,
            calendar_id,
            mid,
            end,
            depth=depth + 1,
        )
        return left + right

    try:
        return _fetch_instance_view_once(
            client, user_access_token, calendar_id, start, end
        )
    except FeishuApiError as e:
        if e.code not in (
            FEISHU_ERR_INSTANCE_VIEW_RANGE,
            FEISHU_ERR_INSTANCE_VIEW_TOO_MANY,
        ):
            raise
        if span <= INSTANCE_VIEW_MIN_SPLIT:
            raise FeishuApiError(
                f"instance_view 无法再缩小窗口: code={e.code} "
                f"{start.isoformat()} .. {end.isoformat()}",
                code=e.code,
            ) from e
        mid = start + span / 2
        log.warning(
            "instance_view code=%s，对半分片 depth=%d span=%s",
            e.code,
            depth,
            span,
        )
        left = _fetch_instance_view_range(
            client,
            user_access_token,
            calendar_id,
            start,
            mid,
            depth=depth + 1,
        )
        right = _fetch_instance_view_range(
            client,
            user_access_token,
            calendar_id,
            mid,
            end,
            depth=depth + 1,
        )
        return left + right


def list_events(
    user_access_token: str,
    calendar_id: str,
    *,
    start: datetime,
    end: datetime,
) -> List[dict]:
    """
    GET /calendar/v4/calendars/{calendar_id}/events/instance_view

    Returns expanded occurrences (and non-recurring events) whose instances
    fall in ``[start, end]``. Sync windows (~67 days) are chunked into
    adjacent slices of at most 39 days, then merged/deduped by ``event_id``.

    Cancelled instances are skipped. On Feishu 193103/193104 the chunk is
    bisected and retried.
    """
    if end < start:
        raise ValueError("list_events: end must be >= start")

    chunks = iter_instance_view_chunks(start, end)
    raw: List[dict] = []
    with httpx.Client(timeout=60.0) as client:
        for c_start, c_end in chunks:
            raw.extend(
                _fetch_instance_view_range(
                    client,
                    user_access_token,
                    calendar_id,
                    c_start,
                    c_end,
                )
            )

    merged = merge_events_by_id(raw)
    # instance_view already scopes by time; keep overlap filter as a safety net
    # for odd boundary / all-day parsing cases.
    results = [ev for ev in merged if event_overlaps_window(ev, start, end)]
    short = calendar_id if len(calendar_id) <= 28 else calendar_id[:28] + "…"
    log.info(
        "日历 %s: 窗内 %d 个实例（原始 %d，分片 %d）",
        short,
        len(results),
        len(raw),
        len(chunks),
    )
    return results


def pull_primary_events(
    user_access_token: str,
    *,
    start: datetime,
    end: datetime,
    exclude_calendar_name: Optional[str] = None,
    skip_subscribed: bool = True,
) -> List[dict]:
    """
    Pull events from Feishu primary calendar only (anti-loop: never from
    the dedicated Outlook Sync target calendar).
    When skip_subscribed is True (default), calendars with role reader /
    free_busy_reader (飞书「订阅」) are excluded from selection/fallback.
    """
    cals = list_calendars(user_access_token)
    # Prefer type=primary; if primary summary equals exclude name, still use
    # primary (source of record) — exclude only applies when listing non-primary.
    cid = primary_calendar_id(cals, skip_subscribed=skip_subscribed)
    if not cid:
        raise FeishuApiError(
            "未找到可用的飞书日历（primary；订阅日历已按配置跳过）"
            if skip_subscribed
            else "未找到可用的飞书日历（primary）"
        )

    # Safety: if somehow primary is the sync target, refuse rather than loop
    if exclude_calendar_name:
        for c in cals:
            cal_id = c.get("calendar_id") or c.get("id")
            if cal_id == cid and calendar_summary(c) == exclude_calendar_name.strip():
                raise FeishuApiError(
                    f"飞书主日历名称与同步目标日历「{exclude_calendar_name}」相同，"
                    "请重命名其一以避免回环"
                )

    events = list_events(
        user_access_token, cid, start=start, end=end
    )
    by_id: Dict[str, dict] = {}
    for ev in events:
        eid = ev.get("event_id")
        if not eid:
            continue
        ev = dict(ev)
        ev["_source_calendar_id"] = cid
        by_id[str(eid)] = ev
    return list(by_id.values())


def create_event(
    user_access_token: str,
    calendar_id: str,
    payload: dict,
) -> dict:
    """POST /calendar/v4/calendars/{calendar_id}/events — returns event dict."""
    encoded_cid = quote(calendar_id, safe="")
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events",
            headers=_headers(user_access_token),
            json=payload,
        )
        try:
            body = resp.json()
        except Exception as e:
            raise FeishuApiError(
                f"create event 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        data = _check(body, "create event")
        ev = (data or {}).get("event") or data or {}
        if not isinstance(ev, dict) or not ev.get("event_id"):
            raise FeishuApiError(f"create event 响应缺少 event_id: {body}")
        return ev


def patch_event(
    user_access_token: str,
    calendar_id: str,
    event_id: str,
    payload: dict,
) -> dict:
    """PATCH /calendar/v4/calendars/{calendar_id}/events/{event_id}."""
    encoded_cid = quote(calendar_id, safe="")
    encoded_eid = quote(event_id, safe="")
    with httpx.Client(timeout=60.0) as client:
        resp = client.patch(
            f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events/{encoded_eid}",
            headers=_headers(user_access_token),
            json=payload,
        )
        try:
            body = resp.json()
        except Exception as e:
            raise FeishuApiError(
                f"patch event 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        data = _check(body, "patch event")
        return (data or {}).get("event") or data or {}


def delete_event(
    user_access_token: str,
    calendar_id: str,
    event_id: str,
) -> None:
    """DELETE /calendar/v4/calendars/{calendar_id}/events/{event_id}."""
    encoded_cid = quote(calendar_id, safe="")
    encoded_eid = quote(event_id, safe="")
    with httpx.Client(timeout=60.0) as client:
        resp = client.delete(
            f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events/{encoded_eid}",
            headers=_headers(user_access_token),
        )
        # 404-ish Feishu codes handled by caller via FeishuApiError
        if resp.status_code == 204 or not resp.content:
            return
        try:
            body = resp.json()
        except Exception as e:
            if resp.status_code < 400:
                return
            raise FeishuApiError(
                f"delete event 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        _check(body, "delete event")


def subscribe_calendar_events(user_access_token: str, calendar_id: str) -> None:
    """
    POST /calendar/v4/calendars/{calendar_id}/events/subscription
    Required before calendar.calendar.event.changed_v4 is delivered for this calendar.
    Uses user_access_token; identity needs reader/writer/owner on the calendar.
    """
    encoded_cid = quote(calendar_id, safe="")
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events/subscription",
            headers=_headers(user_access_token),
        )
        try:
            body = resp.json()
        except Exception as e:
            raise FeishuApiError(
                f"subscribe events 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        _check(body, "subscribe calendar events")
    short = calendar_id if len(calendar_id) <= 28 else calendar_id[:28] + "…"
    log.info("已订阅飞书日历事件变更: %s", short)


def unsubscribe_calendar_events(user_access_token: str, calendar_id: str) -> None:
    """POST /calendar/v4/calendars/{calendar_id}/events/unsubscription"""
    encoded_cid = quote(calendar_id, safe="")
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{API_ROOT}/calendar/v4/calendars/{encoded_cid}/events/unsubscription",
            headers=_headers(user_access_token),
        )
        try:
            body = resp.json()
        except Exception as e:
            if resp.status_code < 400:
                return
            raise FeishuApiError(
                f"unsubscribe events 非 JSON: {resp.status_code} {resp.text[:200]}"
            ) from e
        # Already unsubscribed / not found → treat as success
        code = body.get("code") if isinstance(body, dict) else None
        if code not in (0, None):
            msg = str(body.get("msg") or "")
            if "not" in msg.lower() or code in (191000, 191001, 191002):
                log.info("取消飞书事件订阅可忽略: code=%s", code)
                return
            raise FeishuApiError(
                f"unsubscribe calendar events 失败: code={code} msg={body.get('msg')}"
            )
    short = calendar_id if len(calendar_id) <= 28 else calendar_id[:28] + "…"
    log.info("已取消飞书日历事件订阅: %s", short)


def calendars_for_event_subscription(
    calendars: List[dict],
    *,
    exclude_calendar_name: Optional[str] = None,
    skip_subscribed: bool = True,
) -> List[dict]:
    """
    Calendars to register for Feishu event.changed push.
    Keep primary/owned sync sources; skip reader/free_busy_reader and the
    Outlook→Feishu target calendar (anti-loop).
    """
    cals = filter_calendars_for_sync(calendars, skip_subscribed=skip_subscribed)
    exclude = (exclude_calendar_name or "").strip()
    out: List[dict] = []
    for c in cals:
        if exclude and calendar_summary(c) == exclude:
            log.info(
                "跳过飞书推送订阅（同步目标日历）: %s",
                exclude,
            )
            continue
        # Prefer primary; also allow owned shared calendars used as sources
        role = (c.get("role") or "").strip().lower()
        ctype = (c.get("type") or "").strip().lower()
        if ctype == "primary" or role in ("owner", "writer", ""):
            out.append(c)
    # Prefer primary only when present (matches pull_primary_events source)
    primary = [c for c in out if (c.get("type") or "").lower() == "primary"]
    if primary:
        return primary
    return out[:1]  # fallback: first eligible
