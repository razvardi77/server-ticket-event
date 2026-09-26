from datetime import datetime, timedelta, timezone

import pytest

from openapi_server.impl.showings_impl import HELD, SEAT_LAYOUTS, SHOWINGS, SOLD

SHOWING_FIELDS = {
    "id", "movieTitle", "theaterName", "location", "hallNumber", "startsAt", "pricePerSeat", "currency",
}


def _ids(response):
    return {s["id"] for s in response.json()}


# ---- GET /showings ----
def test_list_all_showings(client):
    r = client.get("/showings")

    assert r.status_code == 200
    assert _ids(r) == {s["id"] for s in SHOWINGS}
    for showing in r.json():
        assert set(showing) == SHOWING_FIELDS  # movieId is internal and never exposed


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"city": "jerusalem"}, {"shw_20511", "shw_50301", "shw_40201"}),
        ({"city": "JERUSALEM"}, {"shw_20511", "shw_50301", "shw_40201"}),
        ({"city": "rishon"}, {"shw_10310", "shw_40202", "shw_20530", "shw_60401"}),
        ({"date": "2026-10-02"}, {"shw_10293", "shw_20511", "shw_30102"}),
        ({"movieId": "mov_dune2"}, {"shw_30101", "shw_30102"}),
        ({"movieId": "mov_interstellar", "city": "rishon"}, {"shw_20530"}),
        ({"date": "2026-10-02", "city": "beer sheva"}, {"shw_30102"}),
    ],
)
def test_list_showings_filters(client, params, expected):
    r = client.get("/showings", params=params)

    assert r.status_code == 200
    assert _ids(r) == expected


def test_list_showings_no_match_is_empty_list(client):
    r = client.get("/showings", params={"city": "Eilat"})

    assert r.status_code == 200
    assert r.json() == []


def test_list_showings_invalid_date(client):
    assert client.get("/showings", params={"date": "02-10-2026"}).status_code == 422


# ---- GET /showings/{showingId} ----
def test_get_showing(client):
    r = client.get("/showings/shw_10293")

    assert r.status_code == 200
    assert r.json() == {
        "id": "shw_10293",
        "movieTitle": "The Fellowship of the Ring",
        "theaterName": "Cinema City Glilot",
        "location": "Glilot, Tel Aviv",
        "hallNumber": 7,
        "startsAt": "2026-10-02T20:30:00+03:00",
        "pricePerSeat": 49.9,
        "currency": "ILS",
    }


def test_get_unknown_showing(client):
    r = client.get("/showings/shw_nope")

    assert r.status_code == 404
    assert r.json() == {"code": "SHOWING_NOT_FOUND", "message": "No showing with id 'shw_nope'."}


# ---- GET /showings/{showingId}/seats ----
@pytest.mark.parametrize("showing_id", sorted(SEAT_LAYOUTS))
def test_seat_map_matches_layout_and_demo_state(client, showing_id):
    r = client.get(f"/showings/{showing_id}/seats")

    assert r.status_code == 200
    rows, per_row = SEAT_LAYOUTS[showing_id]
    statuses = {s["seatNumber"]: s["status"] for s in r.json()}
    assert set(statuses) == {f"{row}{n}" for row in rows for n in range(1, per_row + 1)}
    assert {s for s, st in statuses.items() if st == "SOLD"} == SOLD.get(showing_id, set())
    assert {s for s, st in statuses.items() if st == "HELD"} == set(HELD.get(showing_id, {}))


def test_sold_out_showing(client):
    seats = client.get("/showings/shw_30101/seats").json()

    assert seats and all(s["status"] == "SOLD" for s in seats)


def test_expired_hold_shows_as_available(client, seat_status):
    HELD["shw_40202"] = {"A1": ("ord_old", datetime.now(timezone.utc) - timedelta(seconds=1))}

    assert seat_status("shw_40202", "A1") == "AVAILABLE"
    assert "A1" not in HELD["shw_40202"]


def test_seat_map_unknown_showing(client):
    r = client.get("/showings/shw_nope/seats")

    assert r.status_code == 404
    assert r.json()["code"] == "SHOWING_NOT_FOUND"
