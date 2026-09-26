# server/src/openapi_server/auth.py
#
# User registration, login and JWT handling.
# Not part of openapi.yaml - this module is hand-written, like the impl folder.

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict

import jwt
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from openapi_server.errors import ApiError

# Set JWT_SECRET in the environment for anything beyond local testing.
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-secret-change-me-in-production-please")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

PBKDF2_ITERATIONS = 600_000

# ---- Demo user store (later this will come from a database) ----
# username -> "pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>"
USERS: Dict[str, str] = {}


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


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse)
async def register(body: Credentials) -> RegisterResponse:
    if body.username in USERS:
        raise ApiError(409, "USERNAME_TAKEN", f"Username '{body.username}' is already registered.")
    USERS[body.username] = hash_password(body.password)
    return RegisterResponse(username=body.username)


@router.post("/login", response_model=TokenResponse)
async def login(body: Credentials) -> TokenResponse:
    stored = USERS.get(body.username)
    if stored is None or not verify_password(body.password, stored):
        raise ApiError(401, "INVALID_CREDENTIALS", "Wrong username or password.")
    return TokenResponse(
        access_token=create_access_token(body.username),
        expires_in=JWT_EXPIRE_MINUTES * 60,
    )
