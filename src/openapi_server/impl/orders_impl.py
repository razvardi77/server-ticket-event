# server/src/openapi_server/impl/orders_impl.py
#
# The real logic for the /orders endpoints.
# orders_api.py automatically finds this class because it lives in the impl folder.
#
# Lifecycle: PENDING (seats held) -> CONFIRMED (seats sold)
#                                 -> CANCELLED (DELETE, seats released)
#                                 -> EXPIRED (hold ran out, seats released - no request needed)
# A CONFIRMED order can still be cancelled (refund) until the showing starts.

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from pydantic import validate_email
from pydantic_core import PydanticCustomError

from openapi_server.apis.orders_api_base import BaseOrdersApi
from openapi_server.errors import ApiError
from openapi_server.impl.showings_impl import (
    SHOWINGS,
    SOLD,
    _to_model,
    active_holds,
    seat_exists,
)
from openapi_server.models.order import Order
from openapi_server.models.order_create_request import OrderCreateRequest
from openapi_server.models.order_patch_request import OrderPatchRequest

HOLD_MINUTES = int(os.environ.get("ORDER_HOLD_MINUTES", "10"))

# Demo payment gateway: this token is declined, like Stripe's test token of the same name.
DECLINED_TOKEN = "tok_chargeDeclined"

# ---- Demo order store (later this will come from a database) ----
# orderId -> {"owner": username, "order": Order}
ORDERS: Dict[str, dict] = {}


# ---- Helpers ----
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_showing(showing_id: str) -> dict:
    for s in SHOWINGS:
        if s["id"] == showing_id:
            return s
    raise ApiError(400, "INVALID_SHOWING", f"No showing with id '{showing_id}'.")


def _check_seats(showing_id: str, seats: List[str], order_id: str = None) -> None:
    """400 if the seat list is malformed, 409 if any seat is taken by someone else."""
    if not seats:
        raise ApiError(400, "INVALID_SEATS", "At least one seat is required.")
    if len(set(seats)) != len(seats):
        raise ApiError(400, "INVALID_SEATS", "The same seat appears more than once.")
    bad = [s for s in seats if not seat_exists(showing_id, s)]
    if bad:
        raise ApiError(400, "INVALID_SEATS", f"No such seat(s): {', '.join(bad)}.")

    holds = active_holds(showing_id)
    sold = SOLD.get(showing_id, set())
    taken = [
        s for s in seats
        if s in sold or (s in holds and (holds[s][0] is None or holds[s][0] != order_id))
    ]
    if taken:
        raise ApiError(409, "SEATS_UNAVAILABLE", f"Seat(s) no longer available: {', '.join(taken)}.")


def _hold(order: Order) -> None:
    holds = active_holds(order.showing_id)
    for seat in order.seats:
        holds[seat] = (order.id, order.hold_expires_at)


def _release(order: Order, seats: List[str]) -> None:
    """Drop this order's holds on the given seats (never another order's)."""
    holds = active_holds(order.showing_id)
    for seat in seats:
        if seat in holds and holds[seat][0] == order.id:
            del holds[seat]


def _load(order_id: str, username: str) -> Order:
    """The caller's order, with the hold expiry applied. Other users' orders are 404."""
    entry = ORDERS.get(order_id)
    if entry is None or entry["owner"] != username:
        raise ApiError(404, "ORDER_NOT_FOUND", "The requested order does not exist.")
    order = entry["order"]
    if order.status == "PENDING" and order.hold_expires_at <= _now():
        _release(order, order.seats)
        order.status = "EXPIRED"
    return order


def _require_pending(order: Order) -> None:
    if order.status != "PENDING":
        raise ApiError(409, "ORDER_NOT_PENDING", f"Order is {order.status}, not PENDING.")


# ---- The implementation ----
class OrdersImpl(BaseOrdersApi):

    async def orders_post(self, order_create_request: OrderCreateRequest, username: str) -> Order:
        """POST /orders - create a PENDING order and hold its seats."""
        req = order_create_request
        showing = _get_showing(req.showing_id)
        if datetime.fromisoformat(showing["startsAt"]) <= _now():
            raise ApiError(400, "SHOWING_STARTED", "This showing has already started.")
        _check_seats(req.showing_id, req.seats)

        now = _now()
        order = Order(
            id=f"ord_{secrets.token_hex(6)}",
            status="PENDING",
            showing_id=req.showing_id,
            showing=_to_model(showing),
            seats=list(req.seats),
            total_price=round(showing["pricePerSeat"] * len(req.seats), 2),
            currency=showing["currency"],
            created_at=now,
            hold_expires_at=now + timedelta(minutes=HOLD_MINUTES),
        )
        _hold(order)
        ORDERS[order.id] = {"owner": username, "order": order}
        return order

    async def orders_order_id_get(self, orderId: str, username: str) -> Order:
        """GET /orders/{orderId}"""
        return _load(orderId, username)

    async def orders_order_id_patch(
        self, orderId: str, order_patch_request: OrderPatchRequest, username: str
    ) -> Order:
        """PATCH /orders/{orderId} - change only the fields that were sent."""
        order = _load(orderId, username)
        _require_pending(order)
        req = order_patch_request

        # Validate everything before changing anything.
        if req.seats is not None:
            _check_seats(order.showing_id, req.seats, order_id=order.id)
        if req.contact_email is not None:
            try:
                validate_email(req.contact_email)
            except PydanticCustomError:
                raise ApiError(400, "INVALID_EMAIL", f"'{req.contact_email}' is not a valid email address.")

        if req.seats is not None:
            _release(order, [s for s in order.seats if s not in req.seats])
            order.seats = list(req.seats)
            _hold(order)
            order.total_price = round(order.showing.price_per_seat * len(order.seats), 2)
        if req.passenger_name is not None:
            order.passenger_name = req.passenger_name
        if req.contact_email is not None:
            order.contact_email = req.contact_email
        if req.payment_token is not None:
            order.payment_token = req.payment_token
        return order

    async def orders_order_id_confirm_post(self, orderId: str, username: str) -> Order:
        """POST /orders/{orderId}/confirm - charge the payment token and sell the seats."""
        order = _load(orderId, username)
        _require_pending(order)

        missing = [
            name
            for name, value in [
                ("passengerName", order.passenger_name),
                ("contactEmail", order.contact_email),
                ("paymentToken", order.payment_token),
            ]
            if not value
        ]
        if missing:
            raise ApiError(409, "ORDER_INCOMPLETE", f"Set {', '.join(missing)} with PATCH before confirming.")

        # Stand-in for the payment gateway call.
        if order.payment_token == DECLINED_TOKEN or not order.payment_token.startswith("tok_"):
            raise ApiError(402, "PAYMENT_DECLINED", "The payment gateway declined the charge.")

        _release(order, order.seats)
        SOLD.setdefault(order.showing_id, set()).update(order.seats)
        order.status = "CONFIRMED"
        return order

    async def orders_order_id_delete(self, orderId: str, username: str) -> None:
        """DELETE /orders/{orderId} - cancel; refunds a CONFIRMED order."""
        order = _load(orderId, username)

        if order.status == "PENDING":
            _release(order, order.seats)
        elif order.status == "CONFIRMED":
            if order.showing.starts_at <= _now():
                raise ApiError(409, "ORDER_NOT_CANCELLABLE", "The showing has already started.")
            SOLD.get(order.showing_id, set()).difference_update(order.seats)
            # Stand-in for the payment gateway refund call.
        else:
            raise ApiError(409, "ORDER_NOT_CANCELLABLE", f"Order is already {order.status}.")

        order.status = "CANCELLED"
