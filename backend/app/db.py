"""Database engine and session management.

SQLite is configured with WAL journaling, foreign keys, and a busy timeout so
concurrent readers do not trip over writers during live bidding.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")


def _ensure_sqlite_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite database."""
    if not url.startswith("sqlite"):
        return
    raw_path = url.split("///", 1)[-1]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory(settings.database_url)

_connect_args: dict[str, Any] = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    if not _is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables for the current schema.

    The demo uses ``create_all`` for zero-setup runs. A real deployment would
    switch to Alembic migrations; that trade-off is documented in docs/.
    """
    from . import models  # noqa: F401  (import registers model metadata)

    Base.metadata.create_all(bind=engine)