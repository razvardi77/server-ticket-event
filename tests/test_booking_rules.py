"""Booking rules: future demo dates, no double booking, and the cancellation cutoff."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest

from openapi_server import auth
from openapi_server.impl import orders_impl, showings_impl
from openapi_server.impl.showings_impl import DEMO_DAY_0, HELD, SHOWINGS, SOLD

FREE_SHOWING = "shw_40202"  # 5x8 hall, every seat free
DETAILS = {
    "passengerName": "Rami",
    "contactEmail": "rami@example.com",
    "paymentToken": "tok_visa",
}


def _starts_at(showing_id: str) -> datetime:
    return datetime.fromisoformat(
        next(s for s in SHOWINGS if s["id"] == showing_id)["startsAt"]
    )


def _move_showing(showing_id: str, delta: timedelta) -> None:
    """Make a showing start `delta` from now, in Israel winter time (+02:00)."""
    il = timezone(timedelta(hours=2))
    start = (datetime.now(timezone.utc) + delta).astimezone(il).replace(microsecond=0)
    next(s for s in SHOWINGS if s["id"] == showing_id)["startsAt"] = start.isoformat()


@pytest.fixture
def order_for(client):
    def _order(headers, seats=("A1",), showing_id=FREE_SHOWING, confirm=False) -> dict:
        r = client.post(
            "/orders",
            headers=headers,
            json={"showingId": showing_id, "seats": list(seats)},
        )
        assert r.status_code == 201, r.json()
        order = r.json()
        if confirm:
            assert (
                client.patch(
                    f"/orders/{order['id']}", headers=headers, json=DETAILS
                ).status_code
                == 200
            )
            r = client.post(f"/orders/{order['id']}/confirm", headers=headers)
            assert r.status_code == 200, r.json()
            order = r.json()
        return order

    return _order


@pytest.fixture
def users(login):
    """Eight logged-in users: a list of auth headers."""
    return [login(f"user{i}") for i in range(8)]


@pytest.fixture
def wide_race_window(monkeypatch):
    """Sleep between "the seats are free" and "hold the seats".

    Without BOOKING_LOCK this lets every concurrent request pass the check before any
    of them writes a hold, which is exactly the double-booking race.
    """
    check = orders_impl._check_seats

    def slow_check(*args, **kwargs):
        check(*args, **kwargs)
        time.sleep(0.03)

    monkeypatch.setattr(orders_impl, "_check_seats", slow_check)


def _race(n, request):
    """Run request(i) for i in range(n) in n threads, released at the same moment."""
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait()
        return request(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(run, range(n)))


# ---- 1. Demo showing dates ----
def test_every_demo_showing_is_in_the_future():
    now = datetime.now(timezone.utc)
    for s in SHOWINGS:
        assert _starts_at(s["id"]) > now, s["id"]


def test_demo_showings_are_far_enough_ahead_to_be_cancellable():
    """Day 0 is tomorrow, so every demo order can be cancelled on the day it is made."""
    cutoff = datetime.now(timezone.utc) + timedelta(
        hours=orders_impl.CANCEL_CUTOFF_HOURS
    )
    assert DEMO_DAY_0 > datetime.now(timezone.utc).date()
    assert all(_starts_at(s["id"]) > cutoff for s in SHOWINGS)


def test_demo_showings_keep_israel_local_times():
    starts = {s["id"]: _starts_at(s["id"]) for s in SHOWINGS}

    assert starts["shw_10293"].date() == DEMO_DAY_0
    assert starts["shw_10293"].strftime("%H:%M") == "20:30"
    assert starts["shw_40201"].strftime("%H:%M") == "11:00"
    assert all(
        t.utcoffset() in (timedelta(hours=2), timedelta(hours=3))
        for t in starts.values()
    )


@pytest.mark.parametrize(
    "day, offset",
    [
        ("2026-03-26", 2),  # Thursday before DST
        ("2026-03-27", 3),  # DST starts on the Friday before the last Sunday of March
        ("2026-10-24", 3),
        ("2026-10-25", 2),  # DST ends on the last Sunday of October
        ("2027-03-26", 3),
        ("2027-10-31", 2),
    ],
)
def test_israel_utc_offset(day, offset):
    assert showings_impl._israel_offset(date.fromisoformat(day), 20) == timedelta(
        hours=offset
    )


def test_demo_showings_can_be_booked(client, alice):
    for s in SHOWINGS:
        if s["id"] == "shw_30101":  # the sold-out demo hall
            continue
        r = client.post(
            "/orders", headers=alice, json={"showingId": s["id"], "seats": ["D8"]}
        )
        assert r.status_code in (201, 400), r.json()  # 400 only if the hall has no D8
        assert r.json().get("code") != "SHOWING_STARTED"


# ---- 2. No double booking ----
def test_concurrent_orders_for_the_same_seats_only_one_wins(
    client, users, wide_race_window, seat_status
):
    body = {"showingId": FREE_SHOWING, "seats": ["C1", "C2"]}
    responses = _race(
        len(users), lambda i: client.post("/orders", headers=users[i], json=body)
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * (len(users) - 1)
    assert all(
        r.json()["code"] == "SEATS_UNAVAILABLE"
        for r in responses
        if r.status_code == 409
    )

    winner = next(r.json() for r in responses if r.status_code == 201)
    assert len(orders_impl.ORDERS) == 1
    assert {s: HELD[FREE_SHOWING][s][0] for s in ("C1", "C2")} == {
        "C1": winner["id"],
        "C2": winner["id"],
    }
    assert seat_status(FREE_SHOWING, "C1") == seat_status(FREE_SHOWING, "C2") == "HELD"


def test_concurrent_overlapping_orders_are_all_or_nothing(
    client, users, wide_race_window, seat_status
):
    """Everyone wants C2 plus a seat of their own; one wins, the losers hold nothing."""
    alice, bob = users[:2]
    bodies = [
        (alice, {"showingId": FREE_SHOWING, "seats": ["C1", "C2"]}),
        (bob, {"showingId": FREE_SHOWING, "seats": ["C2", "C3"]}),
    ]
    responses = _race(
        2, lambda i: client.post("/orders", headers=bodies[i][0], json=bodies[i][1])
    )

    assert sorted(r.status_code for r in responses) == [201, 409]
    winner = next(r.json() for r in responses if r.status_code == 201)
    loser_seat = "C3" if winner["seats"] == ["C1", "C2"] else "C1"
    assert seat_status(FREE_SHOWING, "C2") == "HELD"
    assert seat_status(FREE_SHOWING, loser_seat) == "AVAILABLE"


def test_concurrent_seat_change_cannot_steal_a_new_hold(
    client, users, order_for, wide_race_window
):
    """A PATCH onto seats that another user is booking at the same moment: one wins."""
    alice, bob = users[:2]
    bobs_order = order_for(bob, seats=["E1"])
    requests = [
        lambda: client.post(
            "/orders", headers=alice, json={"showingId": FREE_SHOWING, "seats": ["D4"]}
        ),
        lambda: client.patch(
            f"/orders/{bobs_order['id']}", headers=bob, json={"seats": ["D4"]}
        ),
    ]
    responses = _race(2, lambda i: requests[i]())

    winners = [r.json() for r in responses if r.status_code in (200, 201)]
    assert len(winners) == 1
    assert [r.status_code for r in responses if r.status_code == 409] == [409]
    assert HELD[FREE_SHOWING]["D4"][0] == winners[0]["id"]


def test_concurrent_confirms_sell_the_seats_once(client, alice, order_for, monkeypatch):
    order = order_for(alice, seats=["B5"])
    assert (
        client.patch(f"/orders/{order['id']}", headers=alice, json=DETAILS).status_code
        == 200
    )

    release = orders_impl._release
    monkeypatch.setattr(
        orders_impl, "_release", lambda *a: (time.sleep(0.03), release(*a))
    )
    responses = _race(
        4, lambda i: client.post(f"/orders/{order['id']}/confirm", headers=alice)
    )

    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    assert all(
        r.json()["code"] == "ORDER_NOT_PENDING"
        for r in responses
        if r.status_code == 409
    )
    assert "B5" in SOLD[FREE_SHOWING]


def test_concurrent_orders_on_one_event_loop(app, users):
    """The same race through a single asyncio event loop, as uvicorn runs it."""
    body = {"showingId": FREE_SHOWING, "seats": ["A7", "A8"]}

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await asyncio.gather(
                *(ac.post("/orders", headers=h, json=body) for h in users)
            )

    responses = asyncio.run(main())

    assert sorted(r.status_code for r in responses) == [201] + [409] * (len(users) - 1)


def test_seats_freed_by_cancel_can_be_rebooked(client, alice, bob, order_for):
    order = order_for(alice, seats=["E5"], confirm=True)
    assert (
        client.post(
            "/orders", headers=bob, json={"showingId": FREE_SHOWING, "seats": ["E5"]}
        ).status_code
        == 409
    )

    assert client.delete(f"/orders/{order['id']}", headers=alice).status_code == 204
    assert (
        client.post(
            "/orders", headers=bob, json={"showingId": FREE_SHOWING, "seats": ["E5"]}
        ).status_code
        == 201
    )


# ---- 3. Cancellation lock (423 ORDER_LOCKED) ----
# shw_40202 and shw_40201 are both Spirited Away (125 min), at different times.
SPIRITED_RUNTIME = timedelta(minutes=125)
OTHER_SPIRITED = "shw_40201"
LOCKED_PREFIX = (
    "Orders for this showing are locked from 3 hours before it starts until it ends at "
)


def _set_order_start(order_id: str, delta: timedelta) -> datetime:
    """Pretend the order's showing starts `delta` from now (negative = in the past)."""
    start = datetime.now(timezone.utc) + delta
    orders_impl.ORDERS[order_id]["order"].showing.starts_at = start
    return start


def _assert_locked(r, starts_at: datetime):
    assert r.status_code == 423
    body = r.json()
    assert body["code"] == "ORDER_LOCKED"
    assert body["message"].startswith(LOCKED_PREFIX)
    ends_at = datetime.fromisoformat(body["message"].removeprefix(LOCKED_PREFIX)[:-1])
    assert ends_at == starts_at + SPIRITED_RUNTIME


@pytest.mark.parametrize("confirm", [False, True], ids=["pending", "confirmed"])
def test_cancel_locked_less_than_three_hours_before(
    client, alice, order_for, seat_status, confirm
):
    _move_showing(FREE_SHOWING, timedelta(hours=2, minutes=59))
    order = order_for(alice, seats=["A3"], confirm=confirm)

    r = client.delete(f"/orders/{order['id']}", headers=alice)

    _assert_locked(r, datetime.fromisoformat(order["showing"]["startsAt"]))
    # Nothing changed: the order keeps its status and its seats.
    assert client.get(f"/orders/{order['id']}", headers=alice).json()["status"] == (
        order["status"]
    )
    assert seat_status(FREE_SHOWING, "A3") == ("SOLD" if confirm else "HELD")


@pytest.mark.parametrize("confirm", [False, True], ids=["pending", "confirmed"])
def test_cancel_allowed_more_than_three_hours_before(
    client, alice, order_for, seat_status, confirm
):
    _move_showing(FREE_SHOWING, timedelta(hours=3, minutes=1))
    order = order_for(alice, seats=["A3"], confirm=confirm)

    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 204
    assert client.get(f"/orders/{order['id']}", headers=alice).json()["status"] == (
        "CANCELLED"
    )
    assert seat_status(FREE_SHOWING, "A3") == "AVAILABLE"


@pytest.mark.parametrize(
    "starts_in, status, code",
    [
        (timedelta(hours=3, seconds=5), 204, None),  # lock not yet on
        (timedelta(hours=3, seconds=-5), 423, "ORDER_LOCKED"),  # lock starts
        (timedelta(seconds=5), 423, "ORDER_LOCKED"),  # about to start
        (timedelta(minutes=-60), 423, "ORDER_LOCKED"),  # playing right now
        (-SPIRITED_RUNTIME + timedelta(seconds=5), 423, "ORDER_LOCKED"),  # last moment
        (
            -SPIRITED_RUNTIME - timedelta(seconds=5),
            409,
            "ORDER_NOT_CANCELLABLE",
        ),  # ended
    ],
    ids=["before-lock", "lock-starts", "about-to-start", "playing", "ending", "ended"],
)
def test_lock_window_runs_from_cutoff_until_showing_ends(
    client, alice, order_for, seat_status, starts_in, status, code
):
    order = order_for(alice, seats=["A3"], confirm=True)
    _set_order_start(order["id"], starts_in)

    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == status
    if code:
        assert r.json()["code"] == code
        assert seat_status(FREE_SHOWING, "A3") == "SOLD"


def test_after_the_showing_ends_the_lock_is_released(client, alice, order_for):
    """Once the showing is over it is no longer locked; the order is simply finished."""
    order = order_for(alice, confirm=True)
    _set_order_start(order["id"], -SPIRITED_RUNTIME - timedelta(minutes=1))

    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 409
    assert r.json() == {
        "code": "ORDER_NOT_CANCELLABLE",
        "message": "The showing has ended.",
    }


def test_lock_is_per_showing_not_per_movie(client, alice, order_for, seat_status):
    """Locking one Spirited Away showing leaves the other one cancellable."""
    _move_showing(FREE_SHOWING, timedelta(hours=1))
    locked = order_for(alice, seats=["B1"], confirm=True)
    other = order_for(alice, seats=["B1"], showing_id=OTHER_SPIRITED, confirm=True)

    _assert_locked(
        client.delete(f"/orders/{locked['id']}", headers=alice),
        datetime.fromisoformat(locked["showing"]["startsAt"]),
    )
    assert client.delete(f"/orders/{other['id']}", headers=alice).status_code == 204
    assert seat_status(FREE_SHOWING, "B1") == "SOLD"
    assert seat_status(OTHER_SPIRITED, "B1") == "AVAILABLE"


def test_later_showing_of_the_same_movie_is_a_fresh_session(client, alice, order_for):
    """One showing has ended, one is playing (locked), one is tomorrow (open)."""
    ended = order_for(alice, seats=["C1"], confirm=True)
    playing = order_for(alice, seats=["C2"], confirm=True)
    later = order_for(alice, seats=["C1"], showing_id=OTHER_SPIRITED, confirm=True)
    _set_order_start(ended["id"], -SPIRITED_RUNTIME - timedelta(minutes=1))
    start = _set_order_start(playing["id"], timedelta(minutes=-30))

    assert client.delete(f"/orders/{ended['id']}", headers=alice).status_code == 409
    _assert_locked(client.delete(f"/orders/{playing['id']}", headers=alice), start)
    assert client.delete(f"/orders/{later['id']}", headers=alice).status_code == 204


def test_lock_ends_at_uses_each_movies_runtime(client, alice, order_for):
    """shw_20530 is Interstellar (169 min): locked at 168 min in, over at 170."""
    order = order_for(alice, seats=["A1"], showing_id="shw_20530", confirm=True)
    _set_order_start(order["id"], -timedelta(minutes=168))
    assert client.delete(f"/orders/{order['id']}", headers=alice).status_code == 423

    _set_order_start(order["id"], -timedelta(minutes=170))
    assert client.delete(f"/orders/{order['id']}", headers=alice).status_code == 409


def test_every_demo_movie_has_a_runtime():
    assert {s["movieId"] for s in SHOWINGS} <= set(showings_impl.RUNTIME_MINUTES)


def test_already_cancelled_order_is_409_even_inside_the_lock(client, alice, order_for):
    order = order_for(alice, confirm=True)
    assert client.delete(f"/orders/{order['id']}", headers=alice).status_code == 204
    _set_order_start(order["id"], timedelta(hours=1))

    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_CANCELLABLE"


def test_lock_cutoff_is_configurable(client, alice, order_for, monkeypatch):
    monkeypatch.setattr(orders_impl, "CANCEL_CUTOFF_HOURS", 1)
    _move_showing(FREE_SHOWING, timedelta(hours=2))
    order = order_for(alice, confirm=True)

    assert client.delete(f"/orders/{order['id']}", headers=alice).status_code == 204


def test_other_actions_still_work_inside_the_lock(client, alice, order_for):
    """The lock only blocks cancelling: booking, editing and paying stay open."""
    _move_showing(FREE_SHOWING, timedelta(hours=1))
    order = order_for(alice, seats=["B1"])

    r = client.patch(f"/orders/{order['id']}", headers=alice, json={"seats": ["B2"]})
    assert r.status_code == 200
    order = order_for(alice, seats=["B3"], confirm=True)
    assert order["status"] == "CONFIRMED"


def test_concurrent_cancels_inside_the_lock_all_get_423(
    client, alice, order_for, seat_status
):
    _move_showing(FREE_SHOWING, timedelta(hours=1))
    order = order_for(alice, seats=["B4"], confirm=True)

    responses = _race(
        6, lambda i: client.delete(f"/orders/{order['id']}", headers=alice)
    )

    assert [r.status_code for r in responses] == [423] * 6
    assert seat_status(FREE_SHOWING, "B4") == "SOLD"


# ---- Authorization ----
def _expired_token(username):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": username,
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        auth.JWT_SECRET,
        algorithm="HS256",
    )


@pytest.mark.parametrize(
    "headers, code",
    [
        ({}, "UNAUTHORIZED"),
        ({"Authorization": "Bearer not-a-jwt"}, "INVALID_TOKEN"),
        (
            {
                "Authorization": "Bearer "
                + jwt.encode({"sub": "alice"}, "x" * 32, algorithm="HS256")
            },
            "INVALID_TOKEN",
        ),
        ("expired", "TOKEN_EXPIRED"),
    ],
    ids=["no-token", "garbage", "forged", "expired"],
)
@pytest.mark.parametrize("action", ["create", "cancel"])
def test_booking_and_cancelling_require_a_valid_token(
    client, alice, order_for, seat_status, headers, code, action
):
    if headers == "expired":
        headers = {"Authorization": f"Bearer {_expired_token('alice')}"}
    order = order_for(alice, seats=["A4"])

    if action == "create":
        r = client.post(
            "/orders",
            headers=headers,
            json={"showingId": FREE_SHOWING, "seats": ["A5"]},
        )
        assert seat_status(FREE_SHOWING, "A5") == "AVAILABLE"
    else:
        r = client.delete(f"/orders/{order['id']}", headers=headers)
        assert (
            client.get(f"/orders/{order['id']}", headers=alice).json()["status"]
            == "PENDING"
        )

    assert r.status_code == 401
    assert r.json()["code"] == code


def test_other_user_cannot_cancel_even_inside_the_lock(
    client, alice, bob, order_for, seat_status
):
    """Ownership is checked first: bob gets 404, not 423, and learns nothing."""
    _move_showing(FREE_SHOWING, timedelta(hours=1))
    order = order_for(alice, seats=["A6"], confirm=True)

    r = client.delete(f"/orders/{order['id']}", headers=bob)

    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"
    assert seat_status(FREE_SHOWING, "A6") == "SOLD"


def test_other_user_cannot_cancel_to_free_seats(
    client, alice, bob, order_for, seat_status
):
    order = order_for(alice, seats=["A6"], confirm=True)

    assert client.delete(f"/orders/{order['id']}", headers=bob).status_code == 404
    assert (
        client.post(
            "/orders", headers=bob, json={"showingId": FREE_SHOWING, "seats": ["A6"]}
        ).status_code
        == 409
    )
    assert (
        client.get(f"/orders/{order['id']}", headers=alice).json()["status"]
        == "CONFIRMED"
    )


def test_concurrent_cancel_by_owner_and_other_user(client, users, order_for):
    alice, bob = users[:2]
    order = order_for(alice, seats=["D1"], confirm=True)

    requests = [alice, bob, alice, bob]
    responses = _race(
        4, lambda i: client.delete(f"/orders/{order['id']}", headers=requests[i])
    )

    by_user = [(requests[i] is alice, r.status_code) for i, r in enumerate(responses)]
    assert sorted(c for is_alice, c in by_user if not is_alice) == [404, 404]
    assert sorted(c for is_alice, c in by_user if is_alice) == [204, 409]
