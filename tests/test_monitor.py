"""The local monitoring dashboard: seat snapshot, orphan seats, event feed, access."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from openapi_server import monitor
from openapi_server.impl import orders_impl
from openapi_server.impl.showings_impl import SHOWINGS, SOLD

FREE_SHOWING = "shw_40202"  # Spirited Away, 5 rows x 8 seats, every seat free
A, S, H = "AVAILABLE", "SOLD", "HELD"


def _state(client) -> dict:
    r = client.get("/dashboard/api/state")
    assert r.status_code == 200
    return r.json()


def _showing(state, showing_id) -> dict:
    return next(s for s in state["showings"] if s["id"] == showing_id)


def _book(client, headers, seats, showing_id=FREE_SHOWING):
    return client.post(
        "/orders", headers=headers, json={"showingId": showing_id, "seats": seats}
    )


# ---- Orphan seats ----
@pytest.mark.parametrize(
    "row, orphans",
    [
        ([A, A, A, A], []),  # empty row
        ([S, A, S, A, A], [1]),  # boxed in between two taken seats
        ([A, S, A, A], [0]),  # boxed in by the wall and a taken seat
        ([A, A, S, A], [3]),  # wall on the right
        ([S, A, A, S], []),  # a pair of free seats is still sellable
        ([S, A, H, A, S], [1, 3]),  # held seats box in too
        ([A], []),  # a one-seat row is not an orphan
        ([S, S, S], []),  # sold out
    ],
)
def test_find_orphans(row, orphans):
    assert monitor.find_orphans(row) == orphans


def test_demo_data_orphan_is_reported(client):
    """shw_40201 sells B2 and B3, which leaves B1 alone against the wall."""
    shw = _showing(_state(client), "shw_40201")

    assert shw["orphans"] == ["B1"]
    assert shw["rows"][1] == {"row": "B", "seats": [A, S, S, A, A, A], "orphans": [0]}


def test_booking_that_leaves_a_gap_creates_an_orphan(client, alice, bob):
    assert _book(client, alice, ["C1"]).status_code == 201
    assert _showing(_state(client), FREE_SHOWING)["orphans"] == []

    assert _book(client, bob, ["C3", "C4"]).status_code == 201
    state = _state(client)

    assert _showing(state, FREE_SHOWING)["orphans"] == ["C2"]
    assert state["summary"]["orphans"] == 2  # C2 plus the demo orphan B1 in shw_40201


# ---- Occupancy ----
def test_snapshot_counts_seats_per_showing(client, alice):
    _book(client, alice, ["A1", "A2", "A3"])
    shw = _showing(_state(client), FREE_SHOWING)

    assert (shw["capacity"], shw["sold"], shw["held"], shw["available"]) == (
        40,
        0,
        3,
        37,
    )
    assert shw["occupancy"] == 0.075
    assert shw["rows"][0]["seats"][:4] == [H, H, H, A]


def test_snapshot_summary_matches_the_showings(client):
    state = _state(client)
    shows = state["showings"]

    assert {s["id"] for s in shows} == {s["id"] for s in SHOWINGS}
    assert state["summary"]["capacity"] == sum(s["capacity"] for s in shows)
    assert state["summary"]["sold"] == sum(len(v) for v in SOLD.values())
    starts = [datetime.fromisoformat(s["startsAt"]) for s in shows]
    assert starts == sorted(starts)  # soonest first


def test_sold_out_hall_is_full(client):
    shw = _showing(_state(client), "shw_30101")
    assert shw["occupancy"] == 1.0 and shw["available"] == 0


@pytest.mark.parametrize(
    "starts_in, lock",
    [
        (timedelta(hours=5), "open"),
        (timedelta(hours=1), "locked"),
        (timedelta(minutes=-30), "playing"),
        (timedelta(hours=-3), "ended"),
    ],
)
def test_snapshot_shows_the_cancellation_lock(client, starts_in, lock):
    start = datetime.now(timezone.utc) + starts_in
    next(s for s in SHOWINGS if s["id"] == FREE_SHOWING)["startsAt"] = start.isoformat()
    assert _showing(_state(client), FREE_SHOWING)["lock"] == lock


# ---- Event feed ----
def test_conflict_is_recorded_with_code_user_and_seats(client, alice, bob):
    _book(client, alice, ["D1", "D2"])
    _book(client, bob, ["D2", "D3"])

    book_ok, conflict = _state(client)["events"][-2:]
    assert book_ok["status"] == 201 and book_ok["ok"] and book_ok["user"] == "alice"
    assert conflict == {
        **conflict,
        "status": 409,
        "ok": False,
        "action": "book",
        "code": "SEATS_UNAVAILABLE",
        "user": "bob",
        "showingId": FREE_SHOWING,
        "seats": ["D2", "D3"],
    }
    assert "D2" in conflict["message"]


def test_failures_are_recorded_and_counted(client, alice, bob):
    _book(client, alice, ["A1"])  # 201
    _book(client, bob, ["A1"])  # 409
    _book(client, bob, ["Z9"])  # 400
    client.post("/orders", json={"showingId": FREE_SHOWING, "seats": ["A2"]})  # 401
    client.post("/orders", headers=bob, json={"seats": ["A2"]})  # 422
    client.get("/orders/ord_nope", headers=bob)  # 404 on a GET is recorded too
    client.get("/showings")  # a successful read is not

    events = _state(client)["events"]
    assert [(e["status"], e["code"]) for e in events] == [
        (201, None),
        (409, "SEATS_UNAVAILABLE"),
        (400, "INVALID_SEATS"),
        (401, "UNAUTHORIZED"),
        (422, "VALIDATION_ERROR"),
        (404, "ORDER_NOT_FOUND"),
    ]
    summary = _state(client)["summary"]
    assert summary["bookings_ok"] == 1
    assert summary["bookings_failed"] == 4
    assert summary["conflicts"] == 1
    assert summary["failed"] == 5


def test_order_actions_are_labelled(client, alice):
    order = _book(client, alice, ["E1"]).json()
    client.patch(f"/orders/{order['id']}", headers=alice, json={"seats": ["E2"]})
    client.post(f"/orders/{order['id']}/confirm", headers=alice)  # 409 incomplete
    client.delete(f"/orders/{order['id']}", headers=alice)

    events = _state(client)["events"]
    assert [(e["action"], e["status"]) for e in events] == [
        ("book", 201),
        ("change", 200),
        ("confirm", 409),
        ("cancel", 204),
    ]
    assert all(e["orderId"] == order["id"] for e in events[1:])


def test_locked_cancel_is_recorded_as_423(client, alice):
    order = _book(client, alice, ["E5"]).json()
    orders_impl.ORDERS[order["id"]]["order"].showing.starts_at = datetime.now(
        timezone.utc
    ) + timedelta(hours=1)
    client.delete(f"/orders/{order['id']}", headers=alice)

    assert _state(client)["events"][-1]["code"] == "ORDER_LOCKED"


def test_dashboard_requests_are_not_recorded(client):
    client.get("/dashboard")
    client.get("/dashboard/api/state")
    client.get("/dashboard/nope")
    assert _state(client)["events"] == []


def test_event_buffer_is_bounded(client, alice):
    for _ in range(monitor.MAX_EVENTS + 5):
        client.get("/orders/ord_nope", headers=alice)
    assert len(monitor.EVENTS) == monitor.MAX_EVENTS
    assert monitor.TOTALS["failed"] == monitor.MAX_EVENTS + 5


# ---- Live stream ----
class _FakeRequest:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


def _parse(chunk: str):
    fields = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    return fields.get("event"), json.loads(fields["data"]), fields.get("id")


def test_stream_sends_state_then_new_events_as_they_happen(
    client, alice, bob, monkeypatch
):
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0)

    async def run():
        req = _FakeRequest()
        stream = monitor.event_stream(req)
        assert (await anext(stream)).startswith("retry:")
        name, state, _ = _parse(await anext(stream))
        assert name == "state"
        assert _showing(state, FREE_SHOWING)["held"] == 0

        _book(client, alice, ["B5"])
        _book(client, bob, ["B5"])  # 409 while the stream is open

        name, ok, ok_id = _parse(await anext(stream))
        assert (name, ok["status"], ok_id) == ("booking", 201, str(ok["id"]))
        name, conflict, _ = _parse(await anext(stream))
        assert (name, conflict["status"], conflict["code"]) == (
            "booking",
            409,
            "SEATS_UNAVAILABLE",
        )
        name, state, _ = _parse(await anext(stream))
        assert name == "state" and _showing(state, FREE_SHOWING)["held"] == 1

        req.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(run())


def test_stream_resumes_after_last_event_id(client, alice, monkeypatch):
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0)
    _book(client, alice, ["C7"])
    _book(client, alice, ["C7"])
    first, second = monitor.EVENTS

    async def run():
        stream = monitor.event_stream(_FakeRequest(), last_event_id=first["id"])
        await anext(stream)  # retry
        return _parse(await anext(stream))

    name, event, _ = asyncio.run(run())
    assert (name, event["id"]) == ("booking", second["id"])


# ---- Page and access ----
def test_root_redirects_to_dashboard(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/dashboard"


def test_dashboard_page_is_served(client):
    r = client.get("/dashboard")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'new EventSource("/dashboard/events")' in r.text


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_dashboard_open_to_this_machine(app, host):
    assert TestClient(app, client=(host, 5000)).get("/dashboard").status_code == 200


@pytest.mark.parametrize(
    "path", ["/", "/dashboard", "/dashboard/api/state", "/dashboard/events"]
)
def test_dashboard_closed_to_other_machines(app, path):
    r = TestClient(app, client=("192.168.1.20", 5000)).get(path, follow_redirects=False)

    assert r.status_code == 403
    assert r.json()["code"] == "DASHBOARD_LOCAL_ONLY"


def test_dashboard_can_be_opened_to_other_machines(app, monkeypatch):
    monkeypatch.setenv("DASHBOARD_ALLOW_REMOTE", "1")
    remote = TestClient(app, client=("172.17.0.1", 5000))
    assert remote.get("/dashboard/api/state").status_code == 200


def test_api_still_open_to_other_machines(app):
    remote = TestClient(app, client=("192.168.1.20", 5000))
    assert remote.get("/showings").status_code == 200


def test_dashboard_is_not_in_the_openapi_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/dashboard") or p == "/"]
