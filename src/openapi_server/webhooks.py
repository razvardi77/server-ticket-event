# server/src/openapi_server/webhooks.py
#
# Payment gateway webhook. Not part of openapi.yaml - hand-written, like auth.py.
#
# The gateway reports the outcome of a charge; this endpoint only stores that flag
# on the order. It does not charge, refund or change the order's status: the
# background job (jobs.py) reads the flag when the order's hold runs out.
#
# The gateway signs the raw request body with HMAC-SHA256 using the shared
# PAYMENT_WEBHOOK_SECRET and sends the hex digest in X-Webhook-Signature.

import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, Field, ValidationError

from openapi_server.errors import ApiError
from openapi_server.impl.orders_impl import record_payment_status

# Set PAYMENT_WEBHOOK_SECRET in the environment for anything beyond local testing.
WEBHOOK_SECRET = os.environ.get(
    "PAYMENT_WEBHOOK_SECRET", "dev-only-webhook-secret-change-me"
)

router = APIRouter()


class PaymentEvent(BaseModel):
    order_id: str = Field(..., alias="orderId")
    status: Literal["succeeded", "failed"]


def sign(body: bytes, secret: str = None) -> str:
    """The signature the gateway must send for this body."""
    key = (secret or WEBHOOK_SECRET).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


@router.post(
    "/webhooks/payment",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["webhooks"],
    summary="Payment gateway callback: record whether an order's payment succeeded",
)
async def payment_webhook(
    request: Request, x_webhook_signature: str = Header(default="")
) -> Response:
    body = await request.body()
    if not hmac.compare_digest(x_webhook_signature, sign(body)):
        raise ApiError(
            401, "INVALID_SIGNATURE", "The webhook signature is missing or wrong."
        )
    try:
        event = PaymentEvent.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        raise ApiError(
            400,
            "INVALID_EVENT",
            'Expected {"orderId": ..., "status": "succeeded" | "failed"}.',
        )
    record_payment_status(event.order_id, event.status)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
