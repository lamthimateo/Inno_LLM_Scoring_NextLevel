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


def test_validate_endpoint_renders_validation_fragment(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="validate_smoke")

    r = client_with_users.get("/questions/validate_smoke/validate")

    assert r.status_code == 200
    assert 'class="validation-content"' in r.text
    assert "All checks passed" in r.text
    assert "Questions</b> 2" in r.text


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


def test_detail_page_shows_submit_button_for_author_of_draft(client_with_users):
    """Regression: the detail template was comparing current_user.username to
    set.author (a User relationship object), so the Submit-for-review button
    never rendered for the actual author of a draft set."""
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="vis_smoke")
    r = client_with_users.get("/questions/vis_smoke")
    assert r.status_code == 200
    body = r.text
    assert "Submit for review" in body, "author must see the submit-for-review button on a draft"
    assert "/questions/vis_smoke/submit-review" in body


def test_detail_page_hides_submit_button_for_non_author(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="vis_smoke")
    _logout(client_with_users)

    _login(client_with_users, "bob")  # reviewer, not author
    r = client_with_users.get("/questions/vis_smoke")
    assert r.status_code == 200
    assert "Submit for review" not in r.text


def test_detail_history_section_shows_question_edits_and_diff(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="history_smoke")

    r = client_with_users.post(
        "/questions/history_smoke/C1/edit",
        data={
            "prompt": "What is H2O commonly called?",
            "choice_a": "Salt",
            "choice_b": "Water",
            "choice_c": "Sugar",
            "choice_d": "Iron",
            "choice_e": "Oxygen",
            "correct_answer": "B",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    r = client_with_users.get("/questions/history_smoke?section=history")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'aria-selected="true"' in body
    assert "Edit history" in body
    assert "C1" in body
    assert "Snapshot before edit to v2" in body
    assert "/questions/history_smoke/C1/diff?v=1" in body

    r = client_with_users.get("/questions/history_smoke/C1/diff?v=1")
    assert r.status_code == 200, r.text
    assert "What is H2O commonly called?" in r.text


def test_detail_audit_section_shows_set_audit_entries(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="audit_smoke")

    r = client_with_users.post(
        "/questions/audit_smoke/C1/edit",
        data={
            "prompt": "What is H2O commonly called?",
            "choice_a": "Salt",
            "choice_b": "Water",
            "choice_c": "Sugar",
            "choice_d": "Iron",
            "choice_e": "Oxygen",
            "correct_answer": "B",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    r = client_with_users.get("/questions/audit_smoke?section=audit")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Audit log" in body
    assert "alice" in body
    assert "edit_question" in body
    assert "audit_smoke/C1" in body


# ---------------------------------------------------------------------------
# Reviewer picker on the submit-for-review form
# ---------------------------------------------------------------------------


def _user_id(username: str) -> int:
    from sqlalchemy import select as _select
    from src.storage.models import User as _User
    s = db_module.SessionLocal()
    try:
        return s.execute(_select(_User.id).where(_User.username == username)).scalar_one()
    finally:
        s.close()


def test_detail_page_shows_reviewer_picker_with_eligible_users(client_with_users):
    """Author should see a <select name='reviewer_id'> populated with every
    user whose role is reviewer/admin, EXCLUDING themselves."""

    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="picker_smoke")

    r = client_with_users.get("/questions/picker_smoke")
    assert r.status_code == 200
    body = r.text

    assert 'name="reviewer_id"' in body, "reviewer picker must render in the submit form"
    assert ">@bob" in body, "the reviewer 'bob' should be an eligible option"
    assert ">@root" in body, "the admin 'root' should be an eligible option"
    assert ">@alice" not in body, "the author 'alice' must not be offered as their own reviewer"
    # Submit button remains visible (not disabled) when reviewers exist.
    assert "Submit for review" in body
    assert "No eligible reviewer found" not in body


def test_detail_page_shows_no_reviewers_help_when_none_eligible(client_with_users):
    """If the only user is the author, the submit button is disabled and we
    show inline help guiding the author to ask an admin."""

    # Wipe seeded reviewer/admin users; keep only alice (author).
    s = db_module.SessionLocal()
    try:
        from src.storage.models import User as _User
        for username in ("bob", "root"):
            u = s.query(_User).filter_by(username=username).one()
            s.delete(u)
        s.commit()
    finally:
        s.close()

    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="lonely_set")

    r = client_with_users.get("/questions/lonely_set")
    assert r.status_code == 200
    body = r.text

    assert "No eligible reviewer found" in body
    assert 'name="reviewer_id"' not in body, "picker must be hidden when nothing to pick"
    # Submit button is still rendered but disabled.
    assert "Submit for review" in body
    assert "disabled" in body


def test_submit_review_succeeds_with_valid_reviewer(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="happy_path")
    bob_id = _user_id("bob")

    r = client_with_users.post(
        "/questions/happy_path/submit-review",
        data={"reviewer_id": bob_id},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.headers["location"].startswith("/questions/happy_path")
    assert "ok=" in r.headers["location"], "success flash should be present"

    s = db_module.SessionLocal()
    try:
        qs = s.get(QuestionSet, "happy_path")
        assert qs.status == SetStatus.IN_REVIEW.value
        assert qs.reviewer_id == bob_id
    finally:
        s.close()


def test_submit_review_rejects_author_as_reviewer(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="self_review")
    alice_id = _user_id("alice")

    r = client_with_users.post(
        "/questions/self_review/submit-review",
        data={"reviewer_id": alice_id},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303, 400)
    if r.status_code in (302, 303):
        assert "error=" in r.headers["location"]

    s = db_module.SessionLocal()
    try:
        qs = s.get(QuestionSet, "self_review")
        assert qs.status == SetStatus.DRAFT.value
        assert qs.reviewer_id is None
    finally:
        s.close()


def test_submit_review_rejects_non_reviewer_user(client_with_users):
    """A user whose role is neither reviewer nor admin must not be accepted
    as a reviewer for the two-person review rule."""

    # Make a fresh "author-only" user to play the non-reviewer role.
    s = db_module.SessionLocal()
    try:
        register_user(s, username="carol", password="strongpass1", role=UserRole.AUTHOR.value)
        s.commit()
    finally:
        s.close()
    carol_id = _user_id("carol")

    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="bad_reviewer")

    r = client_with_users.post(
        "/questions/bad_reviewer/submit-review",
        data={"reviewer_id": carol_id},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303, 400)
    if r.status_code in (302, 303):
        assert "error=" in r.headers["location"]

    s = db_module.SessionLocal()
    try:
        qs = s.get(QuestionSet, "bad_reviewer")
        assert qs.status == SetStatus.DRAFT.value
        assert qs.reviewer_id is None
    finally:
        s.close()


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


# ---------------------------------------------------------------------------
# POST /questions/import — Save-as-draft form submit
# ---------------------------------------------------------------------------


def test_import_submit_creates_draft_set_with_files(client_with_users):
    _login(client_with_users, "alice")

    r = client_with_users.post(
        "/questions/import",
        data={"set_id": "import_smoke", "title": "Smoke", "description": "desc"},
        files=[("files", ("c1.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.headers["location"].startswith("/questions/import_smoke")

    s = db_module.SessionLocal()
    try:
        from src.storage.models import Question
        qs = s.get(QuestionSet, "import_smoke")
        assert qs is not None
        assert qs.status == SetStatus.DRAFT.value
        assert qs.title == "Smoke"
        qids = {row.qid for row in s.query(Question).filter_by(set_id="import_smoke").all()}
        assert qids == {"C1", "C2"}
    finally:
        s.close()


def test_import_submit_rejects_duplicate_set_id(client_with_users):
    _login(client_with_users, "alice")
    _upload(client_with_users, set_id="dup_set")

    r = client_with_users.post(
        "/questions/import",
        data={"set_id": "dup_set", "title": "Again", "description": ""},
        files=[("files", ("c1.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
        follow_redirects=False,
    )
    # Re-rendered form (no redirect) with a 400 + flash error. Inputs are
    # preserved so the user can correct the Set ID without retyping.
    assert r.status_code == 400, r.text
    assert "already exists" in r.text
    assert 'value="dup_set"' in r.text
    assert 'value="Again"' in r.text


def test_import_submit_rejects_empty_files(client_with_users):
    _login(client_with_users, "alice")

    r = client_with_users.post(
        "/questions/import",
        data={"set_id": "no_files_set", "title": "Empty", "description": ""},
        files=[],
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    assert "at least one .txt" in r.text.lower() or "no .txt files" in r.text.lower()

    s = db_module.SessionLocal()
    try:
        assert s.get(QuestionSet, "no_files_set") is None
    finally:
        s.close()
