# coding: utf-8

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from datetime import date
from typing import List, Optional
from openapi_server.models.error import Error
from openapi_server.models.seat import Seat
from openapi_server.models.showing import Showing


class BaseShowingsApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseShowingsApi.subclasses = BaseShowingsApi.subclasses + (cls,)
    async def showings_get(
        self,
        movie_id: Optional[str],
        var_date: Optional[date],
        city: Optional[str],
    ) -> List[Showing]:
        """Returns the showings scheduled by the cinema, including theater name, location, date and time. The client picks one and passes its id when creating an order. """
        ...


    async def showings_showing_id_get(
        self,
        showingId: str,
    ) -> Showing:
        ...


    async def showings_showing_id_seats_get(
        self,
        showingId: str,
    ) -> List[Seat]:
        """Shows which seats are AVAILABLE, HELD or SOLD."""
        ...
