# server/src/openapi_server/auth.py
#
# User registration, login and JWT handling.
# Not part of openapi.yaml - this module is hand-written, like the impl folder.

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterator, MutableMapping
import jwt
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openapi_server.db import SessionLocal, User, get_session
from openapi_server.errors import ApiError

# Set JWT_SECRET in the environment for anything beyond local testing.
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-secret-change-me-in-production-please")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

PBKDF2_ITERATIONS = 600_000


# ---- User store ----
class UserStore(MutableMapping):
    """Dict-like view of the users table: username -> password hash.

    Each operation runs in its own short session. Request handlers use the
    session from get_session instead; this view is for scripts and tests.
    """

    def __getitem__(self, username: str) -> str:
        with SessionLocal() as session:
            stored = session.scalar(
                select(User.password_hash).where(User.username == username)
            )
        if stored is None:
            raise KeyError(username)
        return stored

    def __setitem__(self, username: str, password_hash: str) -> None:
        with SessionLocal.begin() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                session.add(User(username=username, password_hash=password_hash))
            else:
                user.password_hash = password_hash

    def __delitem__(self, username: str) -> None:
        with SessionLocal.begin() as session:
            result = session.execute(delete(User).where(User.username == username))
        if result.rowcount == 0:
            raise KeyError(username)

    def __iter__(self) -> Iterator[str]:
        with SessionLocal() as session:
            return iter(session.scalars(select(User.username).order_by(User.id)).all())

    def __len__(self) -> int:
        with SessionLocal() as session:
            return session.scalar(select(func.count()).select_from(User))

    def clear(self) -> None:
        with SessionLocal.begin() as session:
            session.execute(delete(User))


USERS = UserStore()


# ---- Password hashing ----
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, iterations, salt_hex, hash_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


# ---- JWT ----
def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Returns the token payload, or raises jwt.PyJWTError if invalid/expired."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]})


# ---- Request / response models ----
class Credentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ---- Endpoints ----
router = APIRouter(tags=["Auth"])


# Plain `def` endpoints: FastAPI runs them in a thread pool, so the blocking
# database calls don't stall the event loop.
@router.post(
    "/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse
)
def register(
    body: Credentials, session: Session = Depends(get_session)
) -> RegisterResponse:
    taken = ApiError(
        409, "USERNAME_TAKEN", f"Username '{body.username}' is already registered."
    )
    if session.scalar(select(User.id).where(User.username == body.username)):
        raise taken
    session.add(
        User(username=body.username, password_hash=hash_password(body.password))
    )
    try:
        session.commit()
    except IntegrityError:
        # Lost a race with a concurrent registration of the same name.
        session.rollback()
        raise taken
    return RegisterResponse(username=body.username)


@router.post("/login", response_model=TokenResponse)
def login(
    body: Credentials, session: Session = Depends(get_session)
) -> TokenResponse:
    stored = session.scalar(
        select(User.password_hash).where(User.username == body.username)
    )
    if stored is None or not verify_password(body.password, stored):
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong username or password.")
    return TokenResponse(
        access_token=create_access_token(body.username),
        expires_in=JWT_EXPIRE_MINUTES * 60,
    )
