"""Users table behaviour. Runs on the in-memory SQLite database set up in conftest."""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from openapi_server import auth
from openapi_server.db import SessionLocal, User


def test_register_inserts_a_row(client):
    r = client.post("/register", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 201

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "alice"))
    assert user.id is not None
    assert isinstance(user.created_at, datetime)
    assert user.password_hash.startswith("pbkdf2_sha256$")
    assert "secret123" not in user.password_hash


def test_username_is_unique_in_the_database():
    with SessionLocal.begin() as session:
        session.add(User(username="alice", password_hash="x"))
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as session:
            session.add(User(username="alice", password_hash="y"))


def test_users_view_reads_and_writes_the_table(client):
    auth.USERS["carol"] = auth.hash_password("secret123")
    assert "carol" in auth.USERS
    assert len(auth.USERS) == 1
    assert list(auth.USERS) == ["carol"]

    # A user added through the view can log in through the API.
    r = client.post("/login", json={"username": "carol", "password": "secret123"})
    assert r.status_code == 200

    del auth.USERS["carol"]
    assert "carol" not in auth.USERS
    with pytest.raises(KeyError):
        del auth.USERS["carol"]
