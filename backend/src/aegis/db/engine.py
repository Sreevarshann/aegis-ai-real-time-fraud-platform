"""Database engine / connection helpers (SQLAlchemy 2.0 Core over psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text

from aegis.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    return create_engine(
        url or get_settings().database_url,
        pool_size=10,
        max_overflow=10,
        pool_pre_ping=True,
        future=True,
    )


@contextmanager
def transaction(engine: Engine | None = None) -> Iterator[Connection]:
    """A connection wrapped in a single transaction (commit on success, rollback on error)."""
    with (engine or get_engine()).begin() as conn:
        yield conn


def ping(engine: Engine | None = None) -> bool:
    try:
        with (engine or get_engine()).connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
