from datetime import datetime, timedelta, timezone

import pytest

from openapi_server.impl import orders_impl
from openapi_server.impl.showings_impl import SHOWINGS

# shw_40202: Spirited Away, Cinema City Rishon LeZion, 38.5 ILS, 5x8 hall, every seat free.
FREE_SHOWING = "shw_40202"
PRICE = 38.5
DETAILS = {"passengerName": "Rami", "contactEmail": "rami@example.com", "paymentToken": "tok_visa"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))  # Python 3.10 has no "Z" support


@pytest.fixture
def create_order(client):
    def _create(headers, seats=("A1", "A2"), showing_id=FREE_SHOWING) -> dict:
        r = client.post("/orders", headers=headers, json={"showingId": showing_id, "seats": list(seats)})
        assert r.status_code == 201, r.json()
        return r.json()

    return _create


@pytest.fixture
def confirmed_order(client, alice, create_order):
    order = create_order(alice)
    client.patch(f"/orders/{order['id']}", headers=alice, json=DETAILS)
    r = client.post(f"/orders/{order['id']}/confirm", headers=alice)
    assert r.status_code == 200
    return r.json()


@pytest.fixture
def expired_order(client, alice, create_order, monkeypatch):
    """An order whose hold ran out the moment it was created."""
    hold_minutes = orders_impl.HOLD_MINUTES
    monkeypatch.setattr(orders_impl, "HOLD_MINUTES", 0)
    order = create_order(alice)
    monkeypatch.setattr(orders_impl, "HOLD_MINUTES", hold_minutes)  # later orders get a normal hold
    return order


# ---- POST /orders ----
def test_create_order(client, alice, create_order, seat_status):
    order = create_order(alice, seats=["B3", "B4"])

    assert order["id"].startswith("ord_")
    assert order["status"] == "PENDING"
    assert order["showingId"] == FREE_SHOWING
    assert order["showing"]["theaterName"] == "Cinema City Rishon LeZion"
    assert order["seats"] == ["B3", "B4"]
    assert order["totalPrice"] == 2 * PRICE
    assert order["currency"] == "ILS"
    hold = _parse(order["holdExpiresAt"]) - _parse(order["createdAt"])
    assert hold == timedelta(minutes=orders_impl.HOLD_MINUTES)
    assert seat_status(FREE_SHOWING, "B3") == seat_status(FREE_SHOWING, "B4") == "HELD"


@pytest.mark.parametrize(
    "showing_id, seats, status, code",
    [
        ("shw_nope", ["A1"], 400, "INVALID_SHOWING"),
        (FREE_SHOWING, [], 400, "INVALID_SEATS"),
        (FREE_SHOWING, ["A1", "A1"], 400, "INVALID_SEATS"),
        (FREE_SHOWING, ["Z1"], 400, "INVALID_SEATS"),
        (FREE_SHOWING, ["A9"], 400, "INVALID_SEATS"),  # hall is 8 seats wide
        (FREE_SHOWING, ["F1"], 400, "INVALID_SEATS"),  # hall has rows A-E
        ("shw_10293", ["A1"], 409, "SEATS_UNAVAILABLE"),  # sold
        ("shw_10293", ["A5"], 409, "SEATS_UNAVAILABLE"),  # permanent demo hold
        ("shw_30101", ["B6"], 409, "SEATS_UNAVAILABLE"),  # sold-out showing
        ("shw_10293", ["C1", "A2"], 409, "SEATS_UNAVAILABLE"),  # one bad seat fails the order
    ],
)
def test_create_order_rejected(client, alice, seat_status, showing_id, seats, status, code):
    r = client.post("/orders", headers=alice, json={"showingId": showing_id, "seats": seats})

    assert r.status_code == status
    assert r.json()["code"] == code
    assert orders_impl.ORDERS == {}
    if showing_id == "shw_10293":
        assert seat_status("shw_10293", "C1") == "AVAILABLE"  # nothing partially held


def test_create_order_seat_held_by_other_user(client, alice, bob, create_order):
    create_order(alice, seats=["C3"])
    r = client.post("/orders", headers=bob, json={"showingId": FREE_SHOWING, "seats": ["C3", "C4"]})

    assert r.status_code == 409
    assert "C3" in r.json()["message"]


def test_create_order_for_started_showing(client, alice):
    next(s for s in SHOWINGS if s["id"] == FREE_SHOWING)["startsAt"] = "2020-01-01T20:00:00+02:00"
    r = client.post("/orders", headers=alice, json={"showingId": FREE_SHOWING, "seats": ["A1"]})

    assert r.status_code == 400
    assert r.json()["code"] == "SHOWING_STARTED"


@pytest.mark.parametrize("body", [{"seats": ["A1"]}, {"showingId": FREE_SHOWING}, {}])
def test_create_order_missing_fields(client, alice, body):
    assert client.post("/orders", headers=alice, json=body).status_code == 422


def test_create_order_requires_auth(client):
    r = client.post("/orders", json={"showingId": FREE_SHOWING, "seats": ["A1"]})

    assert r.status_code == 401


# ---- GET /orders/{orderId} ----
def test_get_own_order(client, alice, create_order):
    order = create_order(alice)
    r = client.get(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 200
    assert r.json() == order


@pytest.mark.parametrize("method", ["get", "patch", "delete", "confirm"])
def test_other_users_order_is_not_found(client, alice, bob, create_order, method):
    order_id = create_order(alice)["id"]
    url = f"/orders/{order_id}"
    if method == "get":
        r = client.get(url, headers=bob)
    elif method == "patch":
        r = client.patch(url, headers=bob, json={"passengerName": "Bob"})
    elif method == "delete":
        r = client.delete(url, headers=bob)
    else:
        r = client.post(f"{url}/confirm", headers=bob)

    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"
    assert client.get(url, headers=alice).json()["status"] == "PENDING"


def test_get_unknown_order(client, alice):
    r = client.get("/orders/ord_nope", headers=alice)

    assert r.status_code == 404
    assert r.json() == {"code": "ORDER_NOT_FOUND", "message": "The requested order does not exist."}


# ---- PATCH /orders/{orderId} ----
def test_patch_changes_only_sent_fields(client, alice, create_order):
    order = create_order(alice)
    client.patch(f"/orders/{order['id']}", headers=alice, json={"passengerName": "Rami"})
    r = client.patch(f"/orders/{order['id']}", headers=alice, json={"contactEmail": "rami@example.com"})

    assert r.status_code == 200
    body = r.json()
    assert body["passengerName"] == "Rami"
    assert body["contactEmail"] == "rami@example.com"
    assert body["seats"] == order["seats"]
    assert body["totalPrice"] == order["totalPrice"]


def test_patch_empty_body_changes_nothing(client, alice, create_order):
    order = create_order(alice)
    r = client.patch(f"/orders/{order['id']}", headers=alice, json={})

    assert r.status_code == 200
    assert r.json() == order


def test_patch_seats_moves_holds_and_reprices(client, alice, create_order, seat_status):
    order = create_order(alice, seats=["A1", "A2"])
    r = client.patch(f"/orders/{order['id']}", headers=alice, json={"seats": ["A2", "A3", "A4"]})

    assert r.status_code == 200
    assert r.json()["seats"] == ["A2", "A3", "A4"]
    assert r.json()["totalPrice"] == 3 * PRICE
    assert seat_status(FREE_SHOWING, "A1") == "AVAILABLE"
    assert all(seat_status(FREE_SHOWING, s) == "HELD" for s in ["A2", "A3", "A4"])


def test_patch_seats_taken_by_other_user(client, alice, bob, create_order):
    create_order(bob, seats=["E1"])
    order = create_order(alice, seats=["A1"])
    r = client.patch(f"/orders/{order['id']}", headers=alice, json={"seats": ["E1"]})

    assert r.status_code == 409
    assert r.json()["code"] == "SEATS_UNAVAILABLE"


def test_patch_invalid_seats(client, alice, create_order):
    order = create_order(alice)
    r = client.patch(f"/orders/{order['id']}", headers=alice, json={"seats": ["A99"]})

    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_SEATS"


def test_patch_is_all_or_nothing(client, alice, create_order, seat_status):
    order = create_order(alice, seats=["A1"])
    r = client.patch(
        f"/orders/{order['id']}",
        headers=alice,
        json={"seats": ["D1"], "passengerName": "Rami", "contactEmail": "not-an-email"},
    )

    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_EMAIL"
    after = client.get(f"/orders/{order['id']}", headers=alice).json()
    assert after["seats"] == ["A1"]
    assert after["passengerName"] is None
    assert seat_status(FREE_SHOWING, "D1") == "AVAILABLE"


def test_patch_confirmed_order(client, alice, confirmed_order):
    r = client.patch(f"/orders/{confirmed_order['id']}", headers=alice, json={"passengerName": "X"})

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_PENDING"


# ---- POST /orders/{orderId}/confirm ----
def test_confirm_order(client, alice, create_order, seat_status):
    order = create_order(alice, seats=["C1", "C2"])
    client.patch(f"/orders/{order['id']}", headers=alice, json=DETAILS)
    r = client.post(f"/orders/{order['id']}/confirm", headers=alice)

    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"
    assert seat_status(FREE_SHOWING, "C1") == seat_status(FREE_SHOWING, "C2") == "SOLD"


@pytest.mark.parametrize("missing", ["passengerName", "contactEmail", "paymentToken"])
def test_confirm_incomplete_order(client, alice, create_order, missing):
    order = create_order(alice)
    client.patch(f"/orders/{order['id']}", headers=alice, json={k: v for k, v in DETAILS.items() if k != missing})
    r = client.post(f"/orders/{order['id']}/confirm", headers=alice)

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_INCOMPLETE"
    assert missing in r.json()["message"]


@pytest.mark.parametrize("token", ["tok_chargeDeclined", "4111111111111111"])
def test_confirm_payment_declined(client, alice, create_order, seat_status, token):
    order = create_order(alice, seats=["A1"])
    client.patch(f"/orders/{order['id']}", headers=alice, json={**DETAILS, "paymentToken": token})
    r = client.post(f"/orders/{order['id']}/confirm", headers=alice)

    assert r.status_code == 402
    assert r.json()["code"] == "PAYMENT_DECLINED"
    assert client.get(f"/orders/{order['id']}", headers=alice).json()["status"] == "PENDING"
    assert seat_status(FREE_SHOWING, "A1") == "HELD"


def test_confirm_twice(client, alice, confirmed_order):
    r = client.post(f"/orders/{confirmed_order['id']}/confirm", headers=alice)

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_PENDING"


def test_confirm_unknown_order(client, alice):
    assert client.post("/orders/ord_nope/confirm", headers=alice).status_code == 404


# ---- DELETE /orders/{orderId} ----
def test_cancel_pending_order(client, alice, create_order, seat_status):
    order = create_order(alice, seats=["B1"])
    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 204
    assert r.content == b""
    assert client.get(f"/orders/{order['id']}", headers=alice).json()["status"] == "CANCELLED"
    assert seat_status(FREE_SHOWING, "B1") == "AVAILABLE"


def test_cancel_confirmed_order_releases_sold_seats(client, alice, confirmed_order, seat_status):
    r = client.delete(f"/orders/{confirmed_order['id']}", headers=alice)

    assert r.status_code == 204
    assert all(seat_status(FREE_SHOWING, s) == "AVAILABLE" for s in confirmed_order["seats"])


def test_cancel_confirmed_order_after_showing_started(client, alice, confirmed_order, seat_status):
    order = orders_impl.ORDERS[confirmed_order["id"]]["order"]
    order.showing.starts_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    r = client.delete(f"/orders/{confirmed_order['id']}", headers=alice)

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_CANCELLABLE"
    assert seat_status(FREE_SHOWING, confirmed_order["seats"][0]) == "SOLD"


def test_cancel_twice(client, alice, create_order):
    order = create_order(alice)
    client.delete(f"/orders/{order['id']}", headers=alice)
    r = client.delete(f"/orders/{order['id']}", headers=alice)

    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_NOT_CANCELLABLE"


def test_cancel_unknown_order(client, alice):
    assert client.delete("/orders/ord_nope", headers=alice).status_code == 404


# ---- Hold expiry ----
def test_expired_order_status_and_seats(client, alice, expired_order, seat_status):
    assert client.get(f"/orders/{expired_order['id']}", headers=alice).json()["status"] == "EXPIRED"
    assert all(seat_status(FREE_SHOWING, s) == "AVAILABLE" for s in expired_order["seats"])


@pytest.mark.parametrize(
    "method, path, body, code",
    [
        ("patch", "", {"passengerName": "Rami"}, "ORDER_NOT_PENDING"),
        ("post", "/confirm", None, "ORDER_NOT_PENDING"),
        ("delete", "", None, "ORDER_NOT_CANCELLABLE"),
    ],
)
def test_expired_order_cannot_change(client, alice, expired_order, method, path, body, code):
    url = f"/orders/{expired_order['id']}{path}"
    r = client.request(method.upper(), url, headers=alice, json=body)

    assert r.status_code == 409
    assert r.json()["code"] == code


def test_expired_seats_can_be_rebooked_and_stay_held(client, alice, bob, expired_order, create_order, seat_status):
    seat = expired_order["seats"][0]
    create_order(bob, seats=[seat])

    # Loading alice's order applies her expiry; it must not release bob's new hold.
    assert client.get(f"/orders/{expired_order['id']}", headers=alice).json()["status"] == "EXPIRED"
    assert seat_status(FREE_SHOWING, seat) == "HELD"
