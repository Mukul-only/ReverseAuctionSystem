from __future__ import annotations

import os

# Tests must not depend on a developer's .env file. Set this before importing
# the app so Settings picks it up (environment wins over .env).
os.environ.setdefault("SECRET_KEY", "test-only-" + "a" * 64)

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import (  # noqa: E402
    Base,
    configure_sqlite_engine,
    install_guards,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    """Isolated in-memory database with production pragmas and triggers."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configure_sqlite_engine(engine)
    Base.metadata.create_all(bind=engine)
    install_guards(engine)

    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    with test_session() as session:
        yield session

    Base.metadata.drop_all(bind=engine)
    engine.dispose()