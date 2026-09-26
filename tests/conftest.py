import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openapi_server import auth
from openapi_server.impl import orders_impl, showings_impl
from openapi_server.main import app as application

# Module-level demo state. orders_impl imports some of these by name, so they are
# restored in place (never rebound) to keep every reference pointing at the same object.
_SHOWINGS_STATE = ("SHOWINGS", "SEAT_LAYOUTS", "SOLD", "HELD")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Every test starts from the original demo data, with no users or orders."""
    saved = {name: copy.deepcopy(getattr(showings_impl, name)) for name in _SHOWINGS_STATE}
    auth.USERS.clear()
    orders_impl.ORDERS.clear()
    # The real iteration count makes each register/login take ~0.5s.
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1_000)

    yield

    for name, value in saved.items():
        current = getattr(showings_impl, name)
        if isinstance(current, list):
            current[:] = value
        else:
            current.clear()
            current.update(value)
    auth.USERS.clear()
    orders_impl.ORDERS.clear()


@pytest.fixture
def app() -> FastAPI:
    application.dependency_overrides = {}

    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def login(client):
    """login("alice") registers the user and returns ready-to-use auth headers."""

    def _login(username: str = "alice", password: str = "secret123") -> dict:
        assert client.post("/register", json={"username": username, "password": password}).status_code == 201
        r = client.post("/login", json={"username": username, "password": password})
        assert r.status_code == 200
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def alice(login) -> dict:
    return login("alice")


@pytest.fixture
def bob(login) -> dict:
    return login("bob")


@pytest.fixture
def seat_status(client):
    """seat_status("shw_10293", "A1") -> "SOLD" / "HELD" / "AVAILABLE" from the public seat map."""

    def _seat_status(showing_id: str, seat: str) -> str:
        seats = client.get(f"/showings/{showing_id}/seats").json()
        return next(s["status"] for s in seats if s["seatNumber"] == seat)

    return _seat_status
