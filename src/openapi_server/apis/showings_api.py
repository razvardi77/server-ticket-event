# coding: utf-8

from typing import Dict, List  # noqa: F401
import importlib
import pkgutil

from openapi_server.apis.showings_api_base import BaseShowingsApi
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

from datetime import date
from typing import List, Optional
from openapi_server.models.error import Error
from openapi_server.models.seat import Seat
from openapi_server.models.showing import Showing

router = APIRouter()

ns_pkg = openapi_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.get(
    "/showings",
    responses={
        200: {"model": List[Showing], "description": "List of showings"},
    },
    tags=["Showings"],
    summary="List available showings",
    response_model_by_alias=True,
)
async def showings_get(
    movie_id: Optional[str] = Query(None, description="", alias="movieId"),
    var_date: Optional[date] = Query(None, description="", alias="date"),
    city: Optional[str] = Query(None, description="", alias="city"),
) -> List[Showing]:
    """Returns the showings scheduled by the cinema, including theater name, location, date and time. The client picks one and passes its id when creating an order. """
    if not BaseShowingsApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseShowingsApi.subclasses[0]().showings_get(movie_id, var_date, city)


@router.get(
    "/showings/{showingId}",
    responses={
        200: {"model": Showing, "description": "Showing details"},
        404: {"model": Error, "description": "Resource not found"},
    },
    tags=["Showings"],
    summary="Get a single showing",
    response_model_by_alias=True,
)
async def showings_showing_id_get(
    showingId: str = Path(..., description=""),
) -> Showing:
    if not BaseShowingsApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseShowingsApi.subclasses[0]().showings_showing_id_get(showingId)


@router.get(
    "/showings/{showingId}/seats",
    responses={
        200: {"model": List[Seat], "description": "Seat map"},
        404: {"model": Error, "description": "Resource not found"},
    },
    tags=["Showings"],
    summary="Get the seat map for a showing",
    response_model_by_alias=True,
)
async def showings_showing_id_seats_get(
    showingId: str = Path(..., description=""),
) -> List[Seat]:
    """Shows which seats are AVAILABLE, HELD or SOLD."""
    if not BaseShowingsApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseShowingsApi.subclasses[0]().showings_showing_id_seats_get(showingId)
