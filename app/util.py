"""Shared helpers: hashing, time windows, HTML body (ported from CLI tool)."""

from __future__ import annotations

import hashlib
import html
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("util")


def html_escape(text: Optional[str]) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def compute_event_hash(
    summary: str,
    start_key: str,
    end_key: str,
    location: str,
    meeting_url: str,
) -> str:
    payload = "\n".join(
        [
            summary or "",
            start_key or "",
            end_key or "",
            location or "",
            meeting_url or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sync_window(
    past_days: int,
    future_days: int,
    tz_name: str = "Asia/Shanghai",
) -> tuple[datetime, datetime]:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    start = (now - timedelta(days=past_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = (now + timedelta(days=future_days)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    return start, end


def parse_feishu_time(
    time_obj: Optional[dict],
    default_tz: str = "Asia/Shanghai",
) -> tuple[Optional[str], Optional[str], bool]:
    if not time_obj or not isinstance(time_obj, dict):
        return None, default_tz, False

    tz_name = time_obj.get("timezone") or default_tz

    if "date" in time_obj and time_obj["date"]:
        d = str(time_obj["date"])[:10]
        return d, tz_name, True

    # Feishu Open API often uses timestamp (unix seconds string)
    ts = time_obj.get("timestamp")
    if ts is not None and str(ts).strip() != "":
        try:
            epoch = int(str(ts))
            dt = datetime.fromtimestamp(epoch, tz=ZoneInfo(tz_name))
            return dt.strftime("%Y-%m-%dT%H:%M:%S"), tz_name, False
        except (ValueError, OSError, OverflowError):
            pass

    dt_str = time_obj.get("datetime")
    if not dt_str:
        return None, tz_name, False

    wall = _to_graph_wall_clock(str(dt_str), tz_name)
    return wall, tz_name, False


def _to_graph_wall_clock(dt_str: str, tz_name: str) -> str:
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return s[:19] if len(s) >= 19 else s

    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        except Exception:
            pass
    else:
        try:
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass

    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def time_key_for_hash(time_obj: Optional[dict], default_tz: str) -> str:
    val, tz, all_day = parse_feishu_time(time_obj, default_tz)
    if val is None:
        return ""
    prefix = "date:" if all_day else "dt:"
    return f"{prefix}{val}|{tz}"


def extract_location(event: dict) -> str:
    loc = event.get("location")
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        return loc.get("name") or loc.get("address") or ""
    return ""


def extract_meeting_url(event: dict) -> str:
    vchat = event.get("vchat") or {}
    if isinstance(vchat, dict):
        return vchat.get("meeting_url") or ""
    return ""


def extract_organizer(event: dict) -> str:
    org = event.get("event_organizer") or {}
    if isinstance(org, dict):
        return org.get("display_name") or ""
    return ""


def map_show_as(free_busy: Optional[str]) -> str:
    fb = (free_busy or "busy").lower()
    if fb == "free":
        return "free"
    return "busy"


def build_outlook_body_html(event: dict) -> str:
    summary = event.get("summary") or "(无标题)"
    description = event.get("description") or ""
    organizer = extract_organizer(event)
    location = extract_location(event)
    meeting_url = extract_meeting_url(event)
    app_link = event.get("app_link") or ""

    rows = [f"<p><b>主题</b>：{html_escape(summary)}</p>"]
    if organizer:
        rows.append(f"<p><b>组织者</b>：{html_escape(organizer)}</p>")
    if location:
        rows.append(f"<p><b>地点</b>：{html_escape(location)}</p>")
    if description:
        rows.append(f"<p><b>描述</b>：{html_escape(description)}</p>")
    if meeting_url:
        rows.append(
            f'<p><b>视频会议</b>：<a href="{html_escape(meeting_url)}">'
            f"{html_escape(meeting_url)}</a></p>"
        )
    if app_link:
        rows.append(
            f'<p><b>飞书日程链接</b>：<a href="{html_escape(app_link)}">'
            f"{html_escape(app_link)}</a></p>"
        )
    rows.append(
        "<hr/><p><i>此日程由飞书 → Outlook 同步服务自动写入，"
        "请勿在 Outlook 中手动编辑（下次同步可能覆盖）。</i></p>"
    )
    return "\n".join(rows)


def feishu_event_to_graph_payload(
    event: dict,
    *,
    default_tz: str = "Asia/Shanghai",
) -> dict:
    summary = event.get("summary") or "(无标题)"
    start_val, start_tz, start_all_day = parse_feishu_time(
        event.get("start_time"), default_tz
    )
    end_val, end_tz, end_all_day = parse_feishu_time(
        event.get("end_time"), default_tz
    )
    if not start_val or not end_val:
        raise ValueError(f"事件缺少起止时间: {event.get('event_id')} {summary}")

    is_all_day = start_all_day or end_all_day
    location = extract_location(event)
    meeting_url = extract_meeting_url(event)

    if is_all_day:
        start_obj = {
            "dateTime": f"{start_val[:10]}T00:00:00",
            "timeZone": start_tz,
        }
        end_obj = {
            "dateTime": f"{end_val[:10]}T00:00:00",
            "timeZone": end_tz,
        }
    else:
        start_obj = {"dateTime": start_val, "timeZone": start_tz}
        end_obj = {"dateTime": end_val, "timeZone": end_tz}

    payload: dict[str, Any] = {
        "subject": summary,
        "body": {
            "contentType": "HTML",
            "content": build_outlook_body_html(event),
        },
        "start": start_obj,
        "end": end_obj,
        "isAllDay": bool(is_all_day),
        "showAs": map_show_as(event.get("free_busy_status")),
        "isReminderOn": False,
    }
    if location:
        payload["location"] = {"displayName": location}
    elif meeting_url:
        payload["location"] = {"displayName": meeting_url}
    return payload


def event_content_hash(event: dict, default_tz: str) -> str:
    return compute_event_hash(
        summary=event.get("summary") or "",
        start_key=time_key_for_hash(event.get("start_time"), default_tz),
        end_key=time_key_for_hash(event.get("end_time"), default_tz),
        location=extract_location(event),
        meeting_url=extract_meeting_url(event),
    )


# ----- Outlook (Graph) → Feishu payload helpers -----


def _parse_graph_datetime(
    time_obj: Optional[dict],
    *,
    is_all_day: bool,
    default_tz: str,
) -> tuple[Optional[dict], str]:
    """
    Convert Graph start/end {dateTime, timeZone} to Feishu time_info
    {timestamp|date, timezone}. Returns (feishu_time_dict, hash_key).
    """
    if not time_obj or not isinstance(time_obj, dict):
        return None, ""

    tz_name = time_obj.get("timeZone") or default_tz
    dt_raw = (time_obj.get("dateTime") or "").strip()
    if not dt_raw:
        return None, ""

    if is_all_day:
        date_part = dt_raw[:10]
        return {"date": date_part, "timezone": "UTC"}, f"date:{date_part}|UTC"

    # Graph wall-clock in the given timeZone (often without offset)
    s = dt_raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Truncate fractional / odd formats
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None, ""

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(default_tz)
        tz_name = default_tz

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)

    ts = str(int(dt.timestamp()))
    return (
        {"timestamp": ts, "timezone": tz_name},
        f"dt:{dt.strftime('%Y-%m-%dT%H:%M:%S')}|{tz_name}",
    )


def extract_outlook_location(event: dict) -> str:
    loc = event.get("location")
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        return loc.get("displayName") or loc.get("name") or ""
    return ""


def extract_outlook_description(event: dict) -> str:
    preview = (event.get("bodyPreview") or "").strip()
    if preview:
        return preview
    body = event.get("body") or {}
    if isinstance(body, dict):
        content = (body.get("content") or "").strip()
        # Prefer plain text; strip crude HTML tags for Feishu description
        if (body.get("contentType") or "").lower() == "html":
            import re

            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:4000]
        return content[:4000]
    return ""


def build_feishu_description(event: dict) -> str:
    parts = []
    desc = extract_outlook_description(event)
    if desc:
        parts.append(desc)
    link = event.get("webLink") or ""
    if link:
        parts.append(f"Outlook 链接: {link}")
    parts.append(
        "—— 此日程由 Outlook → 飞书 同步服务自动写入，"
        "请勿在「Outlook Sync」日历中手动编辑（下次同步可能覆盖）。"
    )
    return "\n".join(parts)


def graph_event_to_feishu_payload(
    event: dict,
    *,
    default_tz: str = "Asia/Shanghai",
) -> dict:
    """Map normalized Graph event → Feishu create/patch event body."""
    summary = event.get("subject") or "(无标题)"
    is_all_day = bool(event.get("isAllDay"))
    start_obj, _ = _parse_graph_datetime(
        event.get("start"), is_all_day=is_all_day, default_tz=default_tz
    )
    end_obj, _ = _parse_graph_datetime(
        event.get("end"), is_all_day=is_all_day, default_tz=default_tz
    )
    if not start_obj or not end_obj:
        raise ValueError(
            f"Outlook 事件缺少起止时间: {event.get('id')} {summary}"
        )

    payload: dict[str, Any] = {
        "summary": summary[:1000],
        "description": build_feishu_description(event),
        "need_notification": False,
        "start_time": start_obj,
        "end_time": end_obj,
        "free_busy_status": "free"
        if (event.get("showAs") or "").lower() == "free"
        else "busy",
    }
    location = extract_outlook_location(event)
    if location:
        payload["location"] = {"name": location[:512]}
    return payload


def outlook_event_content_hash(event: dict, default_tz: str) -> str:
    is_all_day = bool(event.get("isAllDay"))
    _, start_key = _parse_graph_datetime(
        event.get("start"), is_all_day=is_all_day, default_tz=default_tz
    )
    _, end_key = _parse_graph_datetime(
        event.get("end"), is_all_day=is_all_day, default_tz=default_tz
    )
    return compute_event_hash(
        summary=event.get("subject") or "",
        start_key=start_key,
        end_key=end_key,
        location=extract_outlook_location(event),
        meeting_url="",
    )
