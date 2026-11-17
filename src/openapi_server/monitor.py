"""Local monitoring dashboard: live seat occupancy, booking failures and orphan seats.

    GET /dashboard              the page (also reached from GET /)
    GET /dashboard/api/state    one JSON snapshot: showings, seat grids, recent events
    GET /dashboard/events       Server-Sent Events: "state" when seats change,
                                "booking" for every recorded request, as it happens

Requests are recorded by `record_requests`, an HTTP middleware that main.py installs.
It keeps every order change (POST/PATCH/DELETE under /orders) and every 4xx/5xx
response, with the error code that `errors.ApiError` put on `request.state`.

The dashboard shows usernames and every order, so it only answers clients on this
machine (127.0.0.1 / ::1). Set DASHBOARD_ALLOW_REMOTE=1 to open it up, for example
when the server runs in Docker and the browser is on the host.
"""

import asyncio
import json
import os
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from importlib import resources
from itertools import count
from typing import Deque, List, Optional

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from openapi_server import auth
from openapi_server.errors import ApiError
from openapi_server.impl import orders_impl, showings_impl

MAX_EVENTS = 500
POLL_SECONDS = 0.5  # how often the event stream looks for changes
HEARTBEAT_SECONDS = 15
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# Ring buffer of recorded requests, newest last, and running totals since start-up.
EVENTS: Deque[dict] = deque(maxlen=MAX_EVENTS)
TOTALS: Counter = Counter()
_TOTAL_KEYS = ("requests", "failed", "conflicts", "bookings_ok", "bookings_failed")
_ids = count(1)


# ---- Recording ----
def _username(request: Request) -> Optional[str]:
    """The token's user, if the request carried a valid one (never raises)."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return auth.decode_access_token(header[7:]).get("sub")
    except jwt.PyJWTError:
        return None


def _order_context(path: str, body: bytes) -> dict:
    """showingId and seats for an order request, from its body or the stored order."""
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[1] in orders_impl.ORDERS:
        order = orders_impl.ORDERS[parts[1]]["order"]
        return {
            "orderId": order.id,
            "showingId": order.showing_id,
            "seats": order.seats,
        }
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    seats = data.get("seats")
    return {
        "showingId": data.get("showingId"),
        "seats": seats if isinstance(seats, list) else None,
    }


def _action(method: str, path: str) -> str:
    if path.startswith("/orders"):
        if method == "POST" and path.rstrip("/") == "/orders":
            return "book"
        if path.endswith("/confirm"):
            return "confirm"
        return {"PATCH": "change", "DELETE": "cancel", "GET": "view"}.get(
            method, method
        )
    return path.strip("/").split("/")[0] or "root"


def record(event: dict) -> dict:
    event = {"id": next(_ids), "ts": datetime.now(timezone.utc).isoformat(), **event}
    status = event["status"]
    event["ok"] = status < 400
    EVENTS.append(event)
    TOTALS["requests"] += 1
    TOTALS["failed" if status >= 400 else "succeeded"] += 1
    if status == 409:
        TOTALS["conflicts"] += 1
    if event["action"] == "book":
        TOTALS["bookings_ok" if status < 400 else "bookings_failed"] += 1
    return event


async def record_requests(request: Request, call_next):
    """HTTP middleware: record order changes and every error response."""
    path = request.url.path
    if path.startswith("/dashboard") or path in ("/", "/docs", "/openapi.json"):
        return await call_next(request)

    is_order_change = path.startswith("/orders") and request.method != "GET"
    body = await request.body() if is_order_change else b""
    started = time.perf_counter()
    response = await call_next(request)

    if is_order_change or response.status_code >= 400:
        error = getattr(request.state, "api_error", None)
        if error is None and response.status_code == 422:
            error = ("VALIDATION_ERROR", "The request body or parameters are invalid.")
        record(
            {
                "method": request.method,
                "path": path,
                "action": _action(request.method, path),
                "status": response.status_code,
                "code": error[0] if error else None,
                "message": error[1] if error else None,
                "user": _username(request),
                "ms": round((time.perf_counter() - started) * 1000, 1),
                **(_order_context(path, body) if path.startswith("/orders") else {}),
            }
        )
    return response


# ---- Seat analysis ----
def find_orphans(row: List[str]) -> List[int]:
    """Indexes of orphan seats in one row of statuses.

    An orphan is a single free seat that no group of two can ever take: both sides are
    a taken seat or the end of the row, and at least one side is a taken seat.
    """
    orphans = []
    for i, status in enumerate(row):
        if status != "AVAILABLE":
            continue
        left = row[i - 1] if i > 0 else None
        right = row[i + 1] if i + 1 < len(row) else None
        if left == "AVAILABLE" or right == "AVAILABLE":
            continue
        if left is not None or right is not None:  # not a one-seat row
            orphans.append(i)
    return orphans


def _lock_state(showing: dict, now: datetime) -> str:
    starts = datetime.fromisoformat(showing["startsAt"])
    ends = showings_impl.showing_ends_at(showing["id"], starts)
    if now >= ends:
        return "ended"
    if now >= starts:
        return "playing"
    if now >= starts - timedelta(hours=orders_impl.CANCEL_CUTOFF_HOURS):
        return "locked"
    return "open"


def showing_snapshot(showing: dict, now: datetime) -> dict:
    showing_id = showing["id"]
    rows_letters, per_row = showings_impl.SEAT_LAYOUTS[showing_id]
    sold = showings_impl.SOLD.get(showing_id, set())
    held = showings_impl.active_holds(showing_id)

    rows, orphans = [], []
    counts = Counter()
    for letter in rows_letters:
        statuses = []
        for n in range(1, per_row + 1):
            seat = f"{letter}{n}"
            statuses.append(
                "SOLD" if seat in sold else "HELD" if seat in held else "AVAILABLE"
            )
        row_orphans = find_orphans(statuses)
        orphans += [f"{letter}{i + 1}" for i in row_orphans]
        counts.update(statuses)
        rows.append({"row": letter, "seats": statuses, "orphans": row_orphans})

    capacity = len(rows_letters) * per_row
    return {
        "id": showing_id,
        "movieTitle": showing["movieTitle"],
        "theaterName": showing["theaterName"],
        "hallNumber": showing["hallNumber"],
        "startsAt": showing["startsAt"],
        "lock": _lock_state(showing, now),
        "capacity": capacity,
        "sold": counts["SOLD"],
        "held": counts["HELD"],
        "available": counts["AVAILABLE"],
        "occupancy": round((counts["SOLD"] + counts["HELD"]) / capacity, 4),
        "rows": rows,
        "orphans": orphans,
    }


def snapshot() -> dict:
    """Every showing's seat map, under BOOKING_LOCK so it is never half-updated."""
    now = datetime.now(timezone.utc)
    with showings_impl.BOOKING_LOCK:
        shows = [showing_snapshot(s, now) for s in showings_impl.SHOWINGS]
        orders = Counter(e["order"].status for e in orders_impl.ORDERS.values())
    shows.sort(key=lambda s: datetime.fromisoformat(s["startsAt"]))
    capacity = sum(s["capacity"] for s in shows)
    return {
        "showings": shows,
        "summary": {
            "capacity": capacity,
            "sold": sum(s["sold"] for s in shows),
            "held": sum(s["held"] for s in shows),
            "orphans": sum(len(s["orphans"]) for s in shows),
            "orders": dict(orders),
            **{k: TOTALS[k] for k in _TOTAL_KEYS},
        },
    }


# ---- Routes ----
def local_only(request: Request) -> None:
    if os.environ.get("DASHBOARD_ALLOW_REMOTE") == "1":
        return
    host = request.client.host if request.client else None
    if host not in LOCAL_HOSTS:
        raise ApiError(
            403, "DASHBOARD_LOCAL_ONLY", "The dashboard is only served to 127.0.0.1."
        )


router = APIRouter(include_in_schema=False, dependencies=[Depends(local_only)])


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    page = resources.files("openapi_server").joinpath("dashboard.html").read_text()
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/dashboard/api/state")
async def dashboard_state() -> dict:
    return {**snapshot(), "events": list(EVENTS)[-100:]}


def _sse(event: str, data, event_id: Optional[int] = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def event_stream(request: Request, last_event_id: int = 0):
    """Send the full state first, then only what changed, until the browser leaves."""
    sent_state = None
    last_id = last_event_id
    last_beat = time.monotonic()
    yield "retry: 2000\n\n"
    while True:
        if await request.is_disconnected():
            return
        for event in [e for e in EVENTS if e["id"] > last_id]:
            last_id = event["id"]
            yield _sse("booking", event, event_id=last_id)
        state = snapshot()
        encoded = json.dumps(state, sort_keys=True)
        if encoded != sent_state:
            sent_state = encoded
            yield _sse("state", state)
        if time.monotonic() - last_beat > HEARTBEAT_SECONDS:
            last_beat = time.monotonic()
            yield ": keep-alive\n\n"
        await asyncio.sleep(POLL_SECONDS)


@router.get("/dashboard/events")
async def dashboard_events(request: Request) -> StreamingResponse:
    # On reconnect the browser sends Last-Event-ID, so no booking event is shown twice.
    try:
        last_id = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last_id = 0
    return StreamingResponse(
        event_stream(request, last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def reset() -> None:
    """Forget recorded events and totals (used by the tests)."""
    EVENTS.clear()
    TOTALS.clear()
