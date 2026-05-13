"""SQLAlchemy engine + session factory.

Reads ``DATABASE_URL`` from the environment. In production (docker-compose)
this points at Postgres; in tests we override it to ``sqlite:///:memory:``.

Usage patterns
--------------

FastAPI request dependency::

    from fastapi import Depends
    from src.storage.db import get_session

    @app.get("/something")
    def view(session: Session = Depends(get_session)):
        ...

Background job / script::

    from src.storage.db import session_scope

    with session_scope() as session:
        ...   # commits on success, rolls back on exception
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://benchmark:benchmark@localhost:5432/benchmark",
)


def _build_engine(database_url: str) -> Engine:
    """Build a SQLAlchemy engine with sane defaults for both Postgres and SQLite."""

    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine: Engine = _build_engine(DATABASE_URL)


# Ensure SQLite enforces foreign keys (off by default). No-op on Postgres.
@event.listens_for(Engine, "connect")
def _enable_sqlite_fks(dbapi_connection, _connection_record):
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session, close on teardown.

    The view is responsible for committing (or letting service-layer code
    commit). We deliberately do not auto-commit here so a partial failure
    won't persist half-written state.
    """

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional context manager for scripts / background jobs.

    Commits on success, rolls back on exception, always closes.
    """

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine(database_url: str | None = None) -> None:
    """Rebuild the global engine + sessionmaker. Used by tests.

    Call this after setting ``DATABASE_URL`` for the test suite, e.g.::

        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        reset_engine()
    """

    global engine, SessionLocal, DATABASE_URL
    DATABASE_URL = database_url or os.environ.get("DATABASE_URL", DATABASE_URL)
    engine = _build_engine(DATABASE_URL)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def create_all() -> None:
    """Create every table from the ORM metadata. Used for tests + bootstrap.

    Production uses Alembic migrations (``alembic upgrade head``).
    """

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    """Drop every table. Tests only."""

    Base.metadata.drop_all(bind=engine)
