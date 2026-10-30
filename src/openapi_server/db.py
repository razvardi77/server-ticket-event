# server/src/openapi_server/db.py
#
# SQLAlchemy engine, session factory and ORM tables.
# Not part of openapi.yaml - this module is hand-written, like auth.py.
# The schema itself is managed by Alembic (see alembic/versions/).

import os
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import DateTime, Integer, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

# Default: the docker-compose postgres, reached from the host.
# The compose service overrides it to use the `postgres` hostname.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://tickets:tickets@localhost:5432/tickets"
)


def make_engine(url: str):
    if url.startswith("sqlite"):
        # One shared connection, so an in-memory database survives across
        # sessions and TestClient's worker threads.
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session


# ---- Tables ----
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Same limit as auth.Credentials.username.
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # "pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>"
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
