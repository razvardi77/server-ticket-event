# server/src/openapi_server/impl/showings_impl.py
#
# The real logic for the /showings endpoints.
# The generated files (showings_api.py, showings_api_base.py) stay untouched:
# showings_api.py automatically finds this class because it lives in the impl folder.

from datetime import datetime
from typing import List, Optional

from openapi_server.apis.showings_api_base import BaseShowingsApi
from openapi_server.errors import ApiError
from openapi_server.models.seat import Seat
from openapi_server.models.showing import Showing


# ---- Demo data (later this will come from a database) ----
SHOWINGS = [
    {
        "movieId": "mov_lotr1",
        "id": "shw_10293",
        "movieTitle": "The Fellowship of the Ring",
        "theaterName": "Cinema City Glilot",
        "location": "Glilot, Tel Aviv",
        "hallNumber": 7,
        "startsAt": "2026-10-02T20:30:00+03:00",
        "pricePerSeat": 49.9,
        "currency": "ILS",
    },
    {
        "movieId": "mov_lotr1",
        "id": "shw_10294",
        "movieTitle": "The Fellowship of the Ring",
        "theaterName": "Yes Planet Haifa",
        "location": "Haifa",
        "hallNumber": 3,
        "startsAt": "2026-10-03T18:00:00+03:00",
        "pricePerSeat": 45.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_interstellar",
        "id": "shw_20511",
        "movieTitle": "Interstellar",
        "theaterName": "Lev Smadar",
        "location": "Jerusalem",
        "hallNumber": 1,
        "startsAt": "2026-10-02T21:00:00+03:00",
        "pricePerSeat": 42.0,
        "currency": "ILS",
    },
]

# Which seats are already taken, per showing
SOLD = {"shw_10293": {"A1", "A2", "B3"}, "shw_20511": {"C5", "C6"}}
HELD = {"shw_10293": {"A5", "A6"}}

ROWS = "ABC"
SEATS_PER_ROW = 6


# ---- Helpers ----
def _find_showing(showing_id: str) -> dict:
    for s in SHOWINGS:
        if s["id"] == showing_id:
            return s
    raise ApiError(404, "SHOWING_NOT_FOUND", f"No showing with id '{showing_id}'.")


def _to_model(s: dict) -> Showing:
    data = {k: v for k, v in s.items() if k != "movieId"}  # movieId is internal only
    return Showing.from_dict(data)


# ---- The implementation ----
class ShowingsImpl(BaseShowingsApi):

    async def showings_get(self, movie_id: Optional[str], var_date, city: Optional[str]) -> List[Showing]:
        """GET /showings - all showings, optionally filtered by movie, date and city."""
        result = []
        for s in SHOWINGS:
            if movie_id and s["movieId"] != movie_id:
                continue
            if city and city.lower() not in s["location"].lower():
                continue
            if var_date and datetime.fromisoformat(s["startsAt"]).date() != var_date:
                continue
            result.append(_to_model(s))
        return result  # empty list = 200 with [], not an error

    async def showings_showing_id_get(self, showingId: str) -> Showing:
        """GET /showings/{showingId} - one showing, or 404."""
        return _to_model(_find_showing(showingId))

    async def showings_showing_id_seats_get(self, showingId: str) -> List[Seat]:
        """GET /showings/{showingId}/seats - seat map, or 404."""
        _find_showing(showingId)  # raises 404 if it doesn't exist
        sold = SOLD.get(showingId, set())
        held = HELD.get(showingId, set())

        seats = []
        for row in ROWS:
            for n in range(1, SEATS_PER_ROW + 1):
                number = f"{row}{n}"
                if number in sold:
                    status = "SOLD"
                elif number in held:
                    status = "HELD"
                else:
                    status = "AVAILABLE"
                seats.append(Seat.from_dict({"seatNumber": number, "status": status}))
        return seats
