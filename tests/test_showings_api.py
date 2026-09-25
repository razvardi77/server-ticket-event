# coding: utf-8

from fastapi.testclient import TestClient


from datetime import date  # noqa: F401
from typing import List, Optional  # noqa: F401
from openapi_server.models.error import Error  # noqa: F401
from openapi_server.models.seat import Seat  # noqa: F401
from openapi_server.models.showing import Showing  # noqa: F401


def test_showings_get(client: TestClient):
    """Test case for showings_get

    List available showings
    """
    params = [("movie_id", 'movie_id_example'),     ("var_date", '2013-10-20'),     ("city", 'city_example')]
    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/showings",
    #    headers=headers,
    #    params=params,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_showings_showing_id_get(client: TestClient):
    """Test case for showings_showing_id_get

    Get a single showing
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/showings/{showingId}".format(showingId='showing_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200


def test_showings_showing_id_seats_get(client: TestClient):
    """Test case for showings_showing_id_seats_get

    Get the seat map for a showing
    """

    headers = {
    }
    # uncomment below to make a request
    #response = client.request(
    #    "GET",
    #    "/showings/{showingId}/seats".format(showingId='showing_id_example'),
    #    headers=headers,
    #)

    # uncomment below to assert the status code of the HTTP response
    #assert response.status_code == 200

