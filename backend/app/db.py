"""Database engine and session management.

SQLite is configured with WAL journaling, foreign keys, and a busy timeout so
concurrent readers do not trip over writers during live bidding.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
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


def configure_sqlite_engine(bind: Engine) -> None:
    """Attach SQLite PRAGMAs to an engine exactly once."""
    if bind.dialect.name != "sqlite":
        return
    if getattr(bind, "_ra_sqlite_configured", False):
        return
    bind._ra_sqlite_configured = True  # type: ignore[attr-defined]

    @event.listens_for(bind, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


configure_sqlite_engine(engine)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Database-level immutability guards. These are defense in depth: the hash
# chains in Milestones 6 and 9 are what actually make tampering detectable.
GUARD_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bids_no_update
    BEFORE UPDATE ON bids
    BEGIN
        SELECT RAISE(ABORT, 'bids are immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS bids_no_delete
    BEFORE DELETE ON bids
    BEGIN
        SELECT RAISE(ABORT, 'bids are immutable');
    END
    """,
)


def install_guards(bind: Engine = engine) -> None:
    """Create append-only triggers on SQLite."""
    if bind.dialect.name != "sqlite":
        return
    with bind.begin() as connection:
        for statement in GUARD_STATEMENTS:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind: Engine = engine) -> None:
    """Create tables and install guards.

    The demo uses ``create_all`` for zero-setup runs. A real deployment would
    switch to Alembic migrations; that trade-off is documented in docs/.
    """
    from . import models  # noqa: F401  (import registers model metadata)

    Base.metadata.create_all(bind=bind)
    install_guards(bind)