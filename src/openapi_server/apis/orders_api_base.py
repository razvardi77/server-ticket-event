# coding: utf-8

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from typing import Any
from openapi_server.models.error import Error
from openapi_server.models.order import Order
from openapi_server.models.order_create_request import OrderCreateRequest
from openapi_server.models.order_patch_request import OrderPatchRequest
from openapi_server.security_api import get_token_bearerAuth

class BaseOrdersApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseOrdersApi.subclasses = BaseOrdersApi.subclasses + (cls,)
    async def orders_post(
        self,
        order_create_request: OrderCreateRequest,
    ) -> Order:
        """Creates the order and references the showing by id. Theater name, location, date and time are NOT sent here - they are read from the showing on the server. The response includes holdExpiresAt. """
        ...


    async def orders_order_id_get(
        self,
        orderId: str,
    ) -> Order:
        ...


    async def orders_order_id_delete(
        self,
        orderId: str,
    ) -> None:
        """A deliberate cancellation by the user. Releases the seats and triggers a refund if the order was already paid. This is NOT the same as a hold that simply expired. """
        ...


    async def orders_order_id_patch(
        self,
        orderId: str,
        order_patch_request: OrderPatchRequest,
    ) -> Order:
        """Fills in the order piece by piece while it is still on hold - seats, payment, passenger name. Only the fields you send are changed; everything else stays as it was. Allowed only while status is PENDING. """
        ...


    async def orders_order_id_confirm_post(
        self,
        orderId: str,
    ) -> Order:
        """Finalizes a PENDING order. The server charges the saved payment token through the payment gateway; the gateway and the card companies decide whether the card is valid. On success the status becomes CONFIRMED and the tickets are issued. """
        ...
