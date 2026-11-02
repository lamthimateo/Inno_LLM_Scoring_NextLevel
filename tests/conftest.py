"""Pytest fixtures.

Every test runs against a fresh SQLite in-memory database via SQLAlchemy.
We override the global engine in :mod:`src.storage.db` before importing
anything that touches the DB, so production code does not need a
``database_url`` parameter threaded through.
"""

from __future__ import annotations

import os

import pytest

# Point at SQLite in-memory BEFORE importing src.storage.db so the module-
# level engine binds to the right URL.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, User, UserRole  # noqa: E402


@pytest.fixture
def session():
    """Yield a clean SQLAlchemy session backed by a fresh in-memory DB.

    Each test gets its own engine so test order doesn't matter and rows
    from one test never leak into another.
    """

    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)

    s = db_module.SessionLocal()
    try:
        yield s
        s.rollback()
    finally:
        s.close()
        Base.metadata.drop_all(bind=db_module.engine)


@pytest.fixture
def users(session):
    """Seed two users so tests can use ``author_id=1`` / ``reviewer_id=2``."""

    author = User(
        id=1,
        username="author_user",
        password_hash="x",
        role=UserRole.AUTHOR.value,
    )
    reviewer = User(
        id=2,
        username="reviewer_user",
        password_hash="x",
        role=UserRole.REVIEWER.value,
    )
    session.add_all([author, reviewer])
    session.flush()
    return {"author": author, "reviewer": reviewer}


@pytest.fixture(autouse=True)
def no_real_ollama(monkeypatch):
    """No test may talk to a real Ollama server.

    Model discovery is replaced by an "unreachable" stub for every test.
    Tests that need local models install their own fake with
    ``monkeypatch.setattr(ollama_adapter, "discover_models", ...)``; tests of
    the real function call it with ``httpx.MockTransport``.
    """

    from src.adapters import ollama_adapter

    ollama_adapter.clear_discovery_cache()
    monkeypatch.setattr(
        ollama_adapter,
        "discover_models",
        lambda *a, **kw: ollama_adapter.Discovery(
            base_url="http://ollama.test:11434",
            reachable=False,
            error="Ollama is not reachable at http://ollama.test:11434.",
        ),
    )
