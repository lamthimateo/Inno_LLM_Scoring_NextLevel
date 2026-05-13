"""Integration tests for /questions/* routes."""

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
        register_user(s, username="alice", password="strongpass1", role=UserRole.AUTHOR.value)
        register_user(s, username="bob", password="strongpass1", role=UserRole.REVIEWER.value)
        register_user(s, username="root", password="strongpass1", role=UserRole.ADMIN.value)
        s.commit()
    finally:
        s.close()

    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def _login(client: TestClient, username: str, password: str = "strongpass1") -> None:
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code in (200, 302, 303), r.text


def _logout(client: TestClient) -> None:
    client.post("/auth/logout")


def _upload(client: TestClient, *, set_id: str, title: str = "Demo") -> None:
    r = client.post(
        "/questions/import",
        data={"set_id": set_id, "title": title, "description": "test"},
        files=[("files", ("c1.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


# ---------------------------------------------------------------------------


def test_questions_list_requires_login(client_with_users):
    r = client_with_users.get("/questions", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/auth/login" in r.headers["location"]


def test_import_creates_draft_set_and_redirects_to_detail(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="benchmark_v1")
    r = client_with_users.get("/questions/benchmark_v1")
    assert r.status_code == 200
    assert "benchmark_v1" in r.text
    assert "draft" in r.text.lower()


def test_full_workflow_via_http(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="benchmark_v1")

    # alice (author) submits for review. reviewer_id has to be bob (id=2).
    s = db_module.SessionLocal()
    bob_id = s.execute(
        __import__("sqlalchemy").select(  # type: ignore[attr-defined]
            __import__("src.storage.models", fromlist=["User"]).User.id  # type: ignore[attr-defined]
        ).where(
            __import__("src.storage.models", fromlist=["User"]).User.username == "bob"  # type: ignore[attr-defined]
        )
    ).scalar_one()
    s.close()

    r = client_with_users.post(
        "/questions/benchmark_v1/submit-review",
        data={"reviewer_id": bob_id},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    s = db_module.SessionLocal()
    assert s.get(QuestionSet, "benchmark_v1").status == SetStatus.IN_REVIEW.value
    s.close()

    # alice cannot approve their own set
    r = client_with_users.post("/questions/benchmark_v1/approve", follow_redirects=False)
    assert r.status_code == 403

    # bob (reviewer) approves
    _logout(client_with_users)
    _login(client_with_users, "bob")
    r = client_with_users.post("/questions/benchmark_v1/approve", follow_redirects=False)
    assert r.status_code in (302, 303), r.text

    s = db_module.SessionLocal()
    assert s.get(QuestionSet, "benchmark_v1").status == SetStatus.APPROVED.value
    s.close()

    # bob locks
    r = client_with_users.post("/questions/benchmark_v1/lock", follow_redirects=False)
    assert r.status_code in (302, 303), r.text

    s = db_module.SessionLocal()
    assert s.get(QuestionSet, "benchmark_v1").status == SetStatus.LOCKED.value
    s.close()


def test_self_review_is_rejected_at_route_level(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="benchmark_v1")

    s = db_module.SessionLocal()
    from src.storage.models import User
    alice_id = s.execute(
        __import__("sqlalchemy").select(User.id).where(User.username == "alice")  # type: ignore[attr-defined]
    ).scalar_one()
    s.close()

    r = client_with_users.post(
        "/questions/benchmark_v1/submit-review",
        data={"reviewer_id": alice_id},
        follow_redirects=False,
    )
    # Workflow error -> redirect with error param
    assert r.status_code in (302, 303)
    assert "error" in r.headers["location"]


def test_non_author_cannot_submit_review(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="benchmark_v1")
    _logout(client_with_users)

    _login(client_with_users, "bob")
    r = client_with_users.post(
        "/questions/benchmark_v1/submit-review",
        data={"reviewer_id": 99},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_question_detail_404_for_missing(client_with_users):
    _login(client_with_users, "alice")
    r = client_with_users.get("/questions/nope/Q1")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /questions/preview — HTMX live preview fragment
# ---------------------------------------------------------------------------


SAMPLE_WITH_WARNINGS = """C1. What is H2O?
A. Salt
B. Water
C. Sugar
D. Iron
E. Oxygen
Correct answer: B

C1. Duplicate of C1 — should be flagged.
A. Foo
B. Bar
C. Baz
D. Qux
E. Quux
Correct answer: A

C2. Missing answer line.
A. Alpha
B. Beta
C. Gamma
D. Delta
E. Epsilon
"""


CLEAN_SAMPLE = """C1. Which liquid is essential for life?
A. Sodium chloride solid
B. Pure liquid water at room temperature
C. Crystalline sucrose
D. Metallic iron filings
E. Molecular oxygen gas
Correct answer: B

C2. Which element has atomic number one?
A. Helium (atomic number two)
B. Hydrogen (atomic number one)
C. Lithium (atomic number three)
D. Carbon (atomic number six)
E. Oxygen (atomic number eight)
Correct answer: B
"""


def test_questions_preview_renders_fragment_with_valid_file(client_with_users):
    _login(client_with_users, "alice")
    r = client_with_users.post(
        "/questions/preview",
        files=[("files", ("c1.txt", io.BytesIO(CLEAN_SAMPLE.encode()), "text/plain"))],
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    # Not a full page — the fragment must not pull in the base layout.
    body = r.text
    assert "<html" not in body.lower()
    # Parsed-preview card-header marker + parse counts.
    assert "Parsed preview" in body
    assert "chemistry" in body
    # Both QIDs from CLEAN_SAMPLE land in the preview list.
    assert "C1" in body and "C2" in body
    # Clean payload -> green pass finding.
    assert "All checks passed" in body
    assert "alert-success" in body
    # HX-Trigger header tells listening widgets to re-render.
    assert r.headers.get("hx-trigger") == "set:revalidated"


def test_questions_preview_returns_validation_warnings(client_with_users):
    _login(client_with_users, "alice")
    r = client_with_users.post(
        "/questions/preview",
        files=[
            (
                "files",
                ("bad.txt", io.BytesIO(SAMPLE_WITH_WARNINGS.encode()), "text/plain"),
            )
        ],
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert "Duplicate QIDs" in body
    assert "Missing correct answer" in body
    # Error-level finding -> red alert class.
    assert "alert-error" in body
    assert "alert-warn" in body


def test_questions_preview_handles_empty_payload(client_with_users):
    _login(client_with_users, "alice")
    r = client_with_users.post("/questions/preview", files=[])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "No files selected" in body
    # Still emits the revalidation trigger so the validation widget clears.
    assert r.headers.get("hx-trigger") == "set:revalidated"


def test_questions_preview_requires_login(client_with_users):
    r = client_with_users.post(
        "/questions/preview",
        files=[("files", ("c1.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
        follow_redirects=False,
    )
    # require_login raises 303 to /auth/login (kept consistent with the rest
    # of the questions routes — see test_questions_list_requires_login).
    assert r.status_code in (302, 303, 401)
    if r.status_code in (302, 303):
        assert "/auth/login" in r.headers["location"]
