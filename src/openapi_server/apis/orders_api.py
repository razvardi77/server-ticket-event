# coding: utf-8

from typing import Dict, List  # noqa: F401
import importlib
import pkgutil

from openapi_server.apis.orders_api_base import BaseOrdersApi
import openapi_server.impl

from fastapi import (  # noqa: F401
    APIRouter,
    Body,
    Cookie,
    Depends,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    Security,
    status,
)

from typing import Any
from openapi_server.models.error import Error
from openapi_server.models.order import Order
from openapi_server.models.order_create_request import OrderCreateRequest
from openapi_server.models.order_patch_request import OrderPatchRequest
from openapi_server.models.extra_models import TokenModel  # noqa: F401
from openapi_server.security_api import get_token_bearerAuth

router = APIRouter()

ns_pkg = openapi_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.post(
    "/orders",
    responses={
        201: {"model": Order, "description": "Order created in PENDING state"},
        400: {"model": Error, "description": "Invalid request"},
        409: {"description": "One or more of the requested seats are no longer available"},
    },
    tags=["Orders"],
    summary="Create an order (status PENDING, seats put on hold)",
    response_model_by_alias=True,
)
async def orders_post(
    order_create_request: OrderCreateRequest = Body(..., description=""),
    token_bearerAuth: TokenModel = Security(
        get_token_bearerAuth
    ),
) -> Order:
    """Creates the order and references the showing by id. Theater name, location, date and time are NOT sent here - they are read from the showing on the server. The response includes holdExpiresAt. """
    if not BaseOrdersApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseOrdersApi.subclasses[0]().orders_post(order_create_request)


@router.get(
    "/orders/{orderId}",
    responses={
        200: {"model": Order, "description": "Order details"},
        404: {"model": Error, "description": "Resource not found"},
    },
    tags=["Orders"],
    summary="Get an order and its details",
    response_model_by_alias=True,
)
async def orders_order_id_get(
    orderId: str = Path(..., description=""),
    token_bearerAuth: TokenModel = Security(
        get_token_bearerAuth
    ),
) -> Order:
    if not BaseOrdersApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseOrdersApi.subclasses[0]().orders_order_id_get(orderId)


@router.delete(
    "/orders/{orderId}",
    responses={
        204: {"description": "Order cancelled"},
        404: {"model": Error, "description": "Resource not found"},
        409: {"description": "Order can no longer be cancelled"},
    },
    tags=["Orders"],
    summary="Cancel an order",
    response_model_by_alias=True,
)
async def orders_order_id_delete(
    orderId: str = Path(..., description=""),
    token_bearerAuth: TokenModel = Security(
        get_token_bearerAuth
    ),
) -> None:
    """A deliberate cancellation by the user. Releases the seats and triggers a refund if the order was already paid. This is NOT the same as a hold that simply expired. """
    if not BaseOrdersApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseOrdersApi.subclasses[0]().orders_order_id_delete(orderId)


@router.patch(
    "/orders/{orderId}",
    responses={
        200: {"model": Order, "description": "Updated order"},
        404: {"model": Error, "description": "Resource not found"},
        409: {"description": "Order is not PENDING (already confirmed, cancelled or expired)"},
    },
    tags=["Orders"],
    summary="Update a PENDING order (partial update)",
    response_model_by_alias=True,
)
async def orders_order_id_patch(
    orderId: str = Path(..., description=""),
    order_patch_request: OrderPatchRequest = Body(..., description=""),
    token_bearerAuth: TokenModel = Security(
        get_token_bearerAuth
    ),
) -> Order:
    """Fills in the order piece by piece while it is still on hold - seats, payment, passenger name. Only the fields you send are changed; everything else stays as it was. Allowed only while status is PENDING. """
    if not BaseOrdersApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseOrdersApi.subclasses[0]().orders_order_id_patch(orderId, order_patch_request)


@router.post(
    "/orders/{orderId}/confirm",
    responses={
        200: {"model": Order, "description": "Order confirmed"},
        402: {"description": "Payment declined by the payment gateway"},
        409: {"description": "Order is not PENDING, or the hold has already expired"},
    },
    tags=["Orders"],
    summary="Confirm the order",
    response_model_by_alias=True,
)
async def orders_order_id_confirm_post(
    orderId: str = Path(..., description=""),
    token_bearerAuth: TokenModel = Security(
        get_token_bearerAuth
    ),
) -> Order:
    """Finalizes a PENDING order. The server charges the saved payment token through the payment gateway; the gateway and the card companies decide whether the card is valid. On success the status becomes CONFIRMED and the tickets are issued. """
    if not BaseOrdersApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseOrdersApi.subclasses[0]().orders_order_id_confirm_post(orderId)
