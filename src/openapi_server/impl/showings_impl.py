# server/src/openapi_server/impl/showings_impl.py
#
# The real logic for the /showings endpoints.
# The generated files (showings_api.py, showings_api_base.py) stay untouched:
# showings_api.py automatically finds this class because it lives in the impl folder.

import threading
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from openapi_server.apis.showings_api_base import BaseShowingsApi
from openapi_server.errors import ApiError
from openapi_server.models.seat import Seat
from openapi_server.models.showing import Showing


# ---- Demo data (later this will come from a database) ----
# Two chains: Cinema City and Cinema Planet (formerly Yes Planet).
# Times are Israel local time. The dates are relative to the day the server starts
# (day 0 is tomorrow), so the demo showings always lie in the future.
def _last_sunday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)  # only used for March/October
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _israel_offset(day: date, hour: int) -> timedelta:
    """Israel's UTC offset: +03:00 (IDT) from 02:00 on the Friday before the last Sunday
    of March until 02:00 on the last Sunday of October, +02:00 (IST) otherwise."""
    dst_start = (_last_sunday(day.year, 3) - timedelta(days=2), 2)
    dst_end = (_last_sunday(day.year, 10), 2)
    return timedelta(hours=3 if dst_start <= (day, hour) < dst_end else 2)


# Being an hour off around midnight during DST only moves the demo week by one day.
_TODAY_IL = (datetime.now(timezone.utc) + timedelta(hours=2)).date()
DEMO_DAY_0 = _TODAY_IL + timedelta(days=1)


def _starts_at(days: int, hhmm: str) -> str:
    """ISO 8601 start time `days` after DEMO_DAY_0 at `hhmm` Israel local time."""
    day = DEMO_DAY_0 + timedelta(days=days)
    t = time.fromisoformat(hhmm)
    tz = timezone(_israel_offset(day, t.hour))
    return datetime.combine(day, t, tz).isoformat()


SHOWINGS = [
    # ---- Cinema City ----
    {
        "movieId": "mov_lotr1",
        "id": "shw_10293",
        "movieTitle": "The Fellowship of the Ring",
        "theaterName": "Cinema City Glilot",
        "location": "Glilot, Tel Aviv",
        "hallNumber": 7,
        "startsAt": _starts_at(0, "20:30"),
        "pricePerSeat": 49.9,
        "currency": "ILS",
    },
    {
        "movieId": "mov_dune2",
        "id": "shw_30101",
        "movieTitle": "Dune: Part Two",
        "theaterName": "Cinema City Glilot",
        "location": "Glilot, Tel Aviv",
        "hallNumber": 11,
        "startsAt": _starts_at(4, "22:00"),
        "pricePerSeat": 72.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_interstellar",
        "id": "shw_20511",
        "movieTitle": "Interstellar",
        "theaterName": "Cinema City Jerusalem",
        "location": "Jerusalem",
        "hallNumber": 1,
        "startsAt": _starts_at(0, "21:00"),
        "pricePerSeat": 42.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_oppenheimer",
        "id": "shw_50301",
        "movieTitle": "Oppenheimer",
        "theaterName": "Cinema City Jerusalem",
        "location": "Jerusalem",
        "hallNumber": 9,
        "startsAt": _starts_at(6, "20:15"),
        "pricePerSeat": 52.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_lotr2",
        "id": "shw_10310",
        "movieTitle": "The Two Towers",
        "theaterName": "Cinema City Rishon LeZion",
        "location": "Rishon LeZion",
        "hallNumber": 4,
        "startsAt": _starts_at(2, "19:45"),
        "pricePerSeat": 47.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_spirited",
        "id": "shw_40202",
        "movieTitle": "Spirited Away",
        "theaterName": "Cinema City Rishon LeZion",
        "location": "Rishon LeZion",
        "hallNumber": 6,
        "startsAt": _starts_at(8, "16:30"),
        "pricePerSeat": 38.5,
        "currency": "ILS",
    },
    # ---- Cinema Planet ----
    {
        "movieId": "mov_lotr1",
        "id": "shw_10294",
        "movieTitle": "The Fellowship of the Ring",
        "theaterName": "Cinema Planet Haifa",
        "location": "Haifa",
        "hallNumber": 3,
        "startsAt": _starts_at(1, "18:00"),
        "pricePerSeat": 45.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_interstellar",
        "id": "shw_20530",
        "movieTitle": "Interstellar",
        "theaterName": "Cinema Planet Rishonim",
        "location": "Rishonim, Rishon LeZion",
        "hallNumber": 12,
        "startsAt": _starts_at(3, "21:30"),
        "pricePerSeat": 64.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_inception",
        "id": "shw_60401",
        "movieTitle": "Inception",
        "theaterName": "Cinema Planet Rishonim",
        "location": "Rishonim, Rishon LeZion",
        "hallNumber": 3,
        "startsAt": _starts_at(34, "21:00"),
        "pricePerSeat": 46.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_spirited",
        "id": "shw_40201",
        "movieTitle": "Spirited Away",
        "theaterName": "Cinema Planet Jerusalem",
        "location": "Jerusalem",
        "hallNumber": 2,
        "startsAt": _starts_at(1, "11:00"),
        "pricePerSeat": 36.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_dune2",
        "id": "shw_30102",
        "movieTitle": "Dune: Part Two",
        "theaterName": "Cinema Planet Beer Sheva",
        "location": "Beer Sheva",
        "hallNumber": 5,
        "startsAt": _starts_at(0, "20:00"),
        "pricePerSeat": 39.0,
        "currency": "ILS",
    },
    {
        "movieId": "mov_oppenheimer",
        "id": "shw_50302",
        "movieTitle": "Oppenheimer",
        "theaterName": "Cinema Planet Beer Sheva",
        "location": "Beer Sheva",
        "hallNumber": 8,
        "startsAt": _starts_at(27, "19:00"),
        "pricePerSeat": 44.0,
        "currency": "ILS",
    },
]

# Running time per movie, used to work out when a showing ends. Internal only: the API
# exposes startsAt but no end time. Every movieId in SHOWINGS needs an entry.
RUNTIME_MINUTES: Dict[str, int] = {
    "mov_lotr1": 178,
    "mov_lotr2": 179,
    "mov_dune2": 166,
    "mov_interstellar": 169,
    "mov_oppenheimer": 180,
    "mov_spirited": 125,
    "mov_inception": 148,
}


def showing_ends_at(showing_id: str, starts_at: datetime) -> datetime:
    """When this showing ends: its start time plus its movie's running time."""
    movie_id = next(s["movieId"] for s in SHOWINGS if s["id"] == showing_id)
    return starts_at + timedelta(minutes=RUNTIME_MINUTES[movie_id])


# Seat grid per showing: (row letters, seats per row). Seats are named like "A1".
SEAT_LAYOUTS: Dict[str, Tuple[str, int]] = {
    "shw_10293": ("ABC", 6),
    "shw_30101": ("AB", 6),        # small VIP hall - sold out
    "shw_20511": ("ABCDE", 10),
    "shw_50301": ("ABCDEFG", 10),
    "shw_10310": ("ABCDEF", 10),
    "shw_40202": ("ABCDE", 8),
    "shw_10294": ("ABCD", 8),
    "shw_20530": ("ABCDEFGH", 12),  # large hall
    "shw_60401": ("ABCD", 10),
    "shw_40201": ("ABCD", 6),
    "shw_30102": ("ABCDE", 8),
    "shw_50302": ("ABCDEF", 9),
}

# Which seats are already taken, per showing.
# SOLD: showingId -> {seat}
# HELD: showingId -> {seat: (orderId, expiresAt)}; None/None = a permanent demo hold.
SOLD: Dict[str, Set[str]] = {
    "shw_10293": {"A1", "A2", "B3"},
    "shw_30101": {f"{r}{n}" for r in "AB" for n in range(1, 7)},
    "shw_20511": {"C5", "C6"},
    "shw_50301": {"D4", "D5", "D6", "D7", "E5", "E6", "G1", "G2"},
    "shw_10310": {"D5", "D6", "E5", "E6"},
    "shw_10294": {"B4", "B5"},
    "shw_20530": {"F6", "F7", "F8", "E6", "E7"},
    "shw_40201": {"B2", "B3"},
    "shw_50302": {"C4", "C5", "C6"},
}
# Every read-check-write on SOLD, HELD or an order happens while holding this lock, so
# two requests for the same seats can never both pass the availability check. It is
# re-entrant because helpers like active_holds() also take it. It only protects one
# process: running several workers needs a shared store (e.g. Postgres row locks).
BOOKING_LOCK = threading.RLock()

HELD: Dict[str, Dict[str, Tuple[Optional[str], Optional[datetime]]]] = {
    "shw_10293": {"A5": (None, None), "A6": (None, None)},
    "shw_20530": {"F9": (None, None), "F10": (None, None)},
}


# ---- Helpers ----
def seat_exists(showing_id: str, seat: str) -> bool:
    rows, seats_per_row = SEAT_LAYOUTS[showing_id]
    return len(seat) >= 2 and seat[0] in rows and seat[1:].isdigit() and 1 <= int(seat[1:]) <= seats_per_row


def active_holds(showing_id: str) -> Dict[str, Tuple[Optional[str], Optional[datetime]]]:
    """HELD for one showing, after dropping holds whose time has run out."""
    with BOOKING_LOCK:
        holds = HELD.setdefault(showing_id, {})
        now = datetime.now(timezone.utc)
        expired = [s for s, (_, exp) in holds.items() if exp is not None and exp <= now]
        for seat in expired:
            del holds[seat]
        return holds


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
        with BOOKING_LOCK:
            sold = set(SOLD.get(showingId, set()))
            held = dict(active_holds(showingId))

        seats = []
        rows, seats_per_row = SEAT_LAYOUTS[showingId]
        for row in rows:
            for n in range(1, seats_per_row + 1):
                number = f"{row}{n}"
                if number in sold:
                    status = "SOLD"
                elif number in held:
                    status = "HELD"
                else:
                    status = "AVAILABLE"
                seats.append(Seat.from_dict({"seatNumber": number, "status": status}))
        return seats
