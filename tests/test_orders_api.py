# coding: utf-8

from fastapi.testclient import TestClient


from typing import Any  # noqa: F401
from openapi_server.models.error import Error  # noqa: F401
from openapi_server.models.order import Order  # noqa: F401
from openapi_server.models.order_create_request import OrderCreateRequest  # noqa: F401
from openapi_server.models.order_patch_request import OrderPatchRequest  # noqa: F401


def test_orders_post(client: TestClient):
    """Test case for orders_post

    Create an order (status PENDING, seats put on hold)
    """
    order_create_request = openapi_server.OrderCreateRequest()

    headers = {
        "Authorization": "Bearer special-key",
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/orders",
    #    headers=headers,
    #    json=order_create_request,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_orders_order_id_get(client: TestClient):
    """Test case for orders_order_id_get

    Get an order and its details
    """

    headers = {
        "Authorization": "Bearer special-key",
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/orders/{orderId}".format(orderId='order_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_orders_order_id_delete(client: TestClient):
    """Test case for orders_order_id_delete

    Cancel an order
    """

    headers = {
        "Authorization": "Bearer special-key",
    }
    # uncomment below to make a request
    #response = client.request(
    #    "DELETE",
    #    "/orders/{orderId}".format(orderId='order_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_orders_order_id_patch(client: TestClient):
    """Test case for orders_order_id_patch

    Update a PENDING order (partial update)
    """
    order_patch_request = openapi_server.OrderPatchRequest()

    headers = {
        "Authorization": "Bearer special-key",
    }
    # uncomment below to make a request
    #response = client.request(
    #    "PATCH",
    #    "/orders/{orderId}".format(orderId='order_id_example'),
    #    headers=headers,
    #    json=order_patch_request,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_orders_order_id_confirm_post(client: TestClient):
    """Test case for orders_order_id_confirm_post

    Confirm the order
    """

    headers = {
        "Authorization": "Bearer special-key",
    }
    # uncomment below to make a request
    #response = client.request(
    #    "POST",
    #    "/orders/{orderId}/confirm".format(orderId='order_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200

