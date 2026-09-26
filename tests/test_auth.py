from datetime import datetime, timedelta, timezone

import jwt
import pytest

from openapi_server import auth

# Any authenticated route works for checking the token; a missing order is 404 once auth passes.
PROTECTED = "/orders/ord_missing"


# ---- POST /register ----
def test_register_creates_user(client):
    r = client.post("/register", json={"username": "alice", "password": "secret123"})

    assert r.status_code == 201
    assert r.json() == {"username": "alice"}


def test_register_stores_salted_hash_not_password(client):
    client.post("/register", json={"username": "alice", "password": "secret123"})
    client.post("/register", json={"username": "bob", "password": "secret123"})

    stored = auth.USERS["alice"]
    assert "secret123" not in stored
    assert stored.startswith("pbkdf2_sha256$")
    assert stored != auth.USERS["bob"]  # same password, different salt


def test_register_duplicate_username(client):
    client.post("/register", json={"username": "alice", "password": "secret123"})
    r = client.post("/register", json={"username": "alice", "password": "other-password"})

    assert r.status_code == 409
    assert r.json()["code"] == "USERNAME_TAKEN"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "ab", "password": "secret123"},  # username too short
        {"username": "x" * 33, "password": "secret123"},  # username too long
        {"username": "has space", "password": "secret123"},  # bad characters
        {"username": "alice", "password": "short"},  # password too short
        {"username": "alice"},  # missing password
        {"password": "secret123"},  # missing username
    ],
)
def test_register_rejects_invalid_input(client, body):
    assert client.post("/register", json=body).status_code == 422
    assert auth.USERS == {}


# ---- POST /login ----
def test_login_returns_jwt_for_user(client):
    client.post("/register", json={"username": "alice", "password": "secret123"})
    r = client.post("/login", json={"username": "alice", "password": "secret123"})

    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == auth.JWT_EXPIRE_MINUTES * 60
    assert auth.decode_access_token(body["access_token"])["sub"] == "alice"


@pytest.mark.parametrize(
    "username, password",
    [("alice", "wrong-password"), ("nobody", "secret123")],
)
def test_login_rejects_bad_credentials(client, username, password):
    client.post("/register", json={"username": "alice", "password": "secret123"})
    r = client.post("/login", json={"username": username, "password": password})

    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


# ---- Bearer token checks on protected routes ----
def test_valid_token_is_accepted(client, alice):
    assert client.get(PROTECTED, headers=alice).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic YWxpY2U6c2VjcmV0"}])
def test_missing_bearer_token(client, headers):
    r = client.get(PROTECTED, headers=headers)

    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_malformed_token(client):
    r = client.get(PROTECTED, headers={"Authorization": "Bearer not-a-jwt"})

    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_TOKEN"


def test_token_signed_with_other_secret(client, alice):
    now = datetime.now(timezone.utc)
    forged = jwt.encode({"sub": "alice", "exp": now + timedelta(minutes=5)}, "x" * 32, algorithm="HS256")
    r = client.get(PROTECTED, headers={"Authorization": f"Bearer {forged}"})

    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_TOKEN"


def test_expired_token(client, monkeypatch):
    client.post("/register", json={"username": "alice", "password": "secret123"})
    monkeypatch.setattr(auth, "JWT_EXPIRE_MINUTES", -1)
    token = client.post("/login", json={"username": "alice", "password": "secret123"}).json()["access_token"]

    r = client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["code"] == "TOKEN_EXPIRED"


def test_token_for_deleted_user(client, alice):
    del auth.USERS["alice"]
    r = client.get(PROTECTED, headers=alice)

    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_TOKEN"
