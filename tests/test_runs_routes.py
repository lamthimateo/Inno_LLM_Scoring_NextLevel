"""Integration tests for /runs/* routes."""

from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.auth.service import register_user  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, QuestionSet, SetStatus, UserRole  # noqa: E402
from src.web.app import app  # noqa: E402


SAMPLE = """C1. What is H2O?
A. Salt
B. Water
C. Sugar
D. Iron
E. Oxygen
Correct answer: B

C2. Atomic number of Hydrogen?
A. 0
B. 1
C. 2
D. 6
E. 8
Correct answer: B
"""


@pytest.fixture
def client_with_users():
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)

    s = db_module.SessionLocal()
    try:
        register_user(s, username="mateo", password="strongpass1", role=UserRole.AUTHOR.value)
        register_user(s, username="nikoleta", password="strongpass1", role=UserRole.REVIEWER.value)
        s.commit()
    finally:
        s.close()

    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def _login(client: TestClient, username: str) -> None:
    r = client.post(
        "/auth/login",
        data={"username": username, "password": "strongpass1"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303), r.text


def _logout(client: TestClient) -> None:
    client.post("/auth/logout")


def _import_and_lock_set(client: TestClient, *, set_id: str) -> None:
    """End-to-end lock flow via HTTP: mateo imports, nikoleta reviews+locks."""

    _login(client, "mateo")
    r = client.post(
        "/questions/import",
        data={"set_id": set_id, "title": "bench", "description": "test"},
        files=[("files", ("c1.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    s = db_module.SessionLocal()
    from src.storage.models import User
    from sqlalchemy import select as _select

    nikoleta_id = s.execute(
        _select(User.id).where(User.username == "nikoleta")
    ).scalar_one()
    s.close()

    r = client.post(
        f"/questions/{set_id}/submit-review",
        data={"reviewer_id": nikoleta_id},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    _logout(client)
    _login(client, "nikoleta")

    r = client.post(f"/questions/{set_id}/approve", follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    r = client.post(f"/questions/{set_id}/lock", follow_redirects=False)
    assert r.status_code in (302, 303), r.text

    s = db_module.SessionLocal()
    assert s.get(QuestionSet, set_id).status == SetStatus.LOCKED.value
    s.close()


def test_runs_list_modal_shows_locked_set_authored_by_other_user(client_with_users):
    """Regression: a set authored by user A and locked by user B must show
    up in the new-run modal's set picker for *any* authenticated user — the
    /runs page (which embeds runs/new.html as a modal) must populate
    ``locked_sets`` rather than passing an empty list.
    """

    _import_and_lock_set(client_with_users, set_id="bench")
    # Stay logged in as nikoleta (reviewer, not the author).
    r = client_with_users.get("/runs")
    assert r.status_code == 200
    body = r.text
    # The modal renders an <option> for every locked set.
    assert 'value="bench"' in body, (
        "locked set 'bench' should appear in the new-run modal dropdown"
    )


def test_runs_new_standalone_shows_locked_set_authored_by_other_user(client_with_users):
    """Same invariant for the standalone GET /runs/new page."""

    _import_and_lock_set(client_with_users, set_id="bench")
    r = client_with_users.get("/runs/new")
    assert r.status_code == 200
    assert 'value="bench"' in r.text
