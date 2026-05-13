"""SQLAlchemy engine + session helpers.

Single source of truth for opening a connection to the project database.

Configuration:

- Production: ``DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db``
  set by ``docker-compose.yml``.
- Tests: defaults to in-memory SQLite. Tests should pass an explicit URL
  or rely on the ``setup_test_db`` fixture.

Usage in FastAPI routes::

    from fastapi import Depends
    from sqlalchemy.orm import Session
    from src.storage.db import get_session

    @app.get("/things")
    def list_things(db: Session = Depends(get_session)):
        ...

Usage in non-request code (worker jobs, scripts)::

    with session_scope() as db:
        db.add(thing)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import Base


DEFAULT_DATABASE_URL = "sqlite:///./db/benchmark.sqlite3"


def _resolve_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip()


def _make_engine(url: str | None = None) -> Engine:
    url = url or _resolve_database_url()
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        # Needed when FastAPI's threadpool shares a connection across threads.
        connect_args["check_same_thread"] = False
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for non-request code (workers, scripts, tests).

    Commits on success, rolls back on exception, always closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine(url: str) -> None:
    """Re-bind the global engine + session factory to a different URL.

    Used by tests to point at an in-memory SQLite DB.
    """
    global engine, SessionLocal
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def create_all() -> None:
    """Create every table defined in :mod:`src.storage.models`.

    Convenience for tests + first-boot bootstrap when Alembic is not yet
    set up on the target DB. In production we use Alembic instead.
    """
    Base.metadata.create_all(bind=engine)


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp string. Kept for callers that store text dates."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
