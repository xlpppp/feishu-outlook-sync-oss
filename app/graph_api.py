"""Microsoft Graph calendar helpers (token already obtained)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger("graph_api")

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

# Outlook event subscriptions max ~7 days (10080 minutes) without resource data.
# Renew with a slightly shorter window for safety.
GRAPH_EVENT_SUBSCRIPTION_MAX_MINUTES = 10000


class GraphApiError(RuntimeError):
    pass


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def request(
    method: str,
    path: str,
    *,
    token: str,
    json_body: Any = None,
    params: Optional[dict] = None,
) -> Any:
    url = path if path.startswith("http") else f"{GRAPH_ROOT}{path}"
    with httpx.Client(timeout=60.0) as client:
        resp = client.request(
            method.upper(),
            url,
            headers=_headers(token),
            json=json_body,
            params=params,
        )
    if resp.status_code == 204:
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise GraphApiError(
            f"Graph {method.upper()} {path} → {resp.status_code}: {detail}"
        )
    if not resp.content:
        return None
    return resp.json()


def list_calendars(token: str) -> List[dict]:
    data = request("GET", "/me/calendars", token=token)
    return list((data or {}).get("value") or [])


def get_default_calendar(token: str) -> dict:
    """
    Return Outlook primary / default calendar (isDefaultCalendar or first).
    Do NOT use the Feishu Sync target calendar as source.
    """
    cals = list_calendars(token)
    for c in cals:
        if c.get("isDefaultCalendar") is True:
            return c
    if cals:
        return cals[0]
    raise GraphApiError("未找到 Outlook 默认日历")


def ensure_calendar(name: str, token: str) -> dict:
    for c in list_calendars(token):
        if (c.get("name") or "").strip() == name:
            log.info("使用已有 Outlook 日历: %s", name)
            return c
    log.info("创建 Outlook 日历: %s", name)
    return request("POST", "/me/calendars", token=token, json_body={"name": name})


def create_event(calendar_id: str, body: dict, token: str) -> dict:
    cid = quote(calendar_id, safe="")
    return request(
        "POST",
        f"/me/calendars/{cid}/events",
        token=token,
        json_body=body,
    )


def update_event(event_id: str, body: dict, token: str) -> dict:
    eid = quote(event_id, safe="")
    return request("PATCH", f"/me/events/{eid}", token=token, json_body=body)


def delete_event(event_id: str, token: str) -> None:
    eid = quote(event_id, safe="")
    request("DELETE", f"/me/events/{eid}", token=token)


def _normalize_graph_event(raw: dict) -> Optional[dict]:
    """Normalize Graph event to a stable dict; skip cancelled."""
    if not isinstance(raw, dict):
        return None
    if raw.get("isCancelled") is True:
        return None
    eid = raw.get("id")
    if not eid:
        return None
    loc = raw.get("location") or {}
    body = raw.get("body") or {}
    return {
        "id": str(eid),
        "subject": raw.get("subject") or "",
        "start": raw.get("start") or {},
        "end": raw.get("end") or {},
        "location": loc if isinstance(loc, dict) else {},
        "body": body if isinstance(body, dict) else {},
        "bodyPreview": raw.get("bodyPreview") or "",
        "isCancelled": False,
        "isAllDay": bool(raw.get("isAllDay")),
        "showAs": raw.get("showAs") or "busy",
        "webLink": raw.get("webLink") or "",
    }


def list_events(
    token: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
) -> List[dict]:
    """
    List events in a calendar window via calendarView (expanded instances).
    Returns normalized dicts: id, subject, start, end, location, body, isCancelled.
    """
    cid = quote(calendar_id, safe="")
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    results: List[dict] = []
    path = f"/me/calendars/{cid}/calendarView"
    params: Optional[Dict[str, Any]] = {
        "startDateTime": start_iso,
        "endDateTime": end_iso,
        "$top": "100",
        "$select": (
            "id,subject,start,end,location,body,bodyPreview,"
            "isCancelled,isAllDay,showAs,webLink"
        ),
        "$orderby": "start/dateTime",
    }
    next_url: Optional[str] = None

    while True:
        if next_url:
            data = request("GET", next_url, token=token)
        else:
            data = request("GET", path, token=token, params=params)
        for raw in (data or {}).get("value") or []:
            norm = _normalize_graph_event(raw)
            if norm:
                results.append(norm)
        next_url = (data or {}).get("@odata.nextLink")
        if not next_url:
            break

    short = calendar_id if len(calendar_id) <= 28 else calendar_id[:28] + "…"
    log.info("Outlook 日历 %s: %d 个事件", short, len(results))
    return results


def create_subscription(
    token: str,
    *,
    resource: str,
    notification_url: str,
    client_state: str,
    change_type: str = "created,updated,deleted",
    lifecycle_notification_url: Optional[str] = None,
    expiration_minutes: int = GRAPH_EVENT_SUBSCRIPTION_MAX_MINUTES,
) -> dict:
    """
    POST /subscriptions — Outlook events support /me/events or /users/{id}/events.
    Max lifetime without resource data: under 7 days.
    """
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=max(45, min(expiration_minutes, GRAPH_EVENT_SUBSCRIPTION_MAX_MINUTES))
    )
    body: Dict[str, Any] = {
        "changeType": change_type,
        "notificationUrl": notification_url,
        "resource": resource,
        "expirationDateTime": expires.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
        "clientState": client_state,
    }
    # Same URL is allowed; must be set at create time (cannot PATCH later).
    life_url = lifecycle_notification_url or notification_url
    if life_url:
        body["lifecycleNotificationUrl"] = life_url
    data = request("POST", "/subscriptions", token=token, json_body=body)
    if not isinstance(data, dict) or not data.get("id"):
        raise GraphApiError(f"create subscription 响应缺少 id: {data}")
    log.info(
        "已创建 Graph 订阅 resource=%s id=%s…",
        resource,
        str(data["id"])[:12],
    )
    return data


def renew_subscription(
    token: str,
    subscription_id: str,
    *,
    expiration_minutes: int = GRAPH_EVENT_SUBSCRIPTION_MAX_MINUTES,
) -> dict:
    """PATCH /subscriptions/{id} — extend expirationDateTime."""
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=max(45, min(expiration_minutes, GRAPH_EVENT_SUBSCRIPTION_MAX_MINUTES))
    )
    sid = quote(subscription_id, safe="")
    data = request(
        "PATCH",
        f"/subscriptions/{sid}",
        token=token,
        json_body={
            "expirationDateTime": expires.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
        },
    )
    log.info("已续期 Graph 订阅 id=%s…", subscription_id[:12])
    return data if isinstance(data, dict) else {}


def delete_subscription(token: str, subscription_id: str) -> None:
    """DELETE /subscriptions/{id}"""
    sid = quote(subscription_id, safe="")
    try:
        request("DELETE", f"/subscriptions/{sid}", token=token)
        log.info("已删除 Graph 订阅 id=%s…", subscription_id[:12])
    except GraphApiError as e:
        msg = str(e)
        if "404" in msg:
            log.info("Graph 订阅已不存在 id=%s…", subscription_id[:12])
            return
        raise


def reauthorize_subscription(token: str, subscription_id: str) -> None:
    """POST /subscriptions/{id}/reauthorize — recover from reauthorizationRequired."""
    sid = quote(subscription_id, safe="")
    request("POST", f"/subscriptions/{sid}/reauthorize", token=token)
    log.info("已 reauthorize Graph 订阅 id=%s…", subscription_id[:12])
