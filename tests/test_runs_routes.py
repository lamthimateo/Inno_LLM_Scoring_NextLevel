"""Integration tests for /runs/* routes."""

from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.auth.service import register_user  # noqa: E402
from src.benchmark.runs import clear_cancellation, is_cancellation_requested  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import (  # noqa: E402
    AuditLog,
    Base,
    Job,
    JobStatus,
    QuestionSet,
    Run,
    SetStatus,
    User,
    UserRole,
)
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


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/cancel
# ---------------------------------------------------------------------------


def _insert_queued_run(*, run_id: str, set_id: str, started_by_username: str) -> None:
    """Insert a ``runs`` + companion ``jobs`` row in QUEUED state.

    We avoid going through ``create_run`` + ``run_in_background`` because the
    background thread would try to call the real adapter; the cancel route
    is independent of the orchestrator thread and only inspects the DB.
    """

    from sqlalchemy import select as _select

    s = db_module.SessionLocal()
    try:
        user_id = s.execute(
            _select(User.id).where(User.username == started_by_username)
        ).scalar_one()
        s.add_all(
            [
                Run(run_id=run_id, set_id=set_id, started_by_id=user_id),
                Job(
                    id=run_id,
                    kind="evaluation_run",
                    status=JobStatus.QUEUED.value,
                    set_id=set_id,
                    run_id=run_id,
                    created_by_id=user_id,
                    payload_json={"model_ids": ["fake:m1"]},
                    progress_total=1,
                    progress_done=0,
                ),
            ]
        )
        s.commit()
    finally:
        s.close()


def test_cancel_route_marks_run_as_cancelled_and_303(client_with_users):
    """Owner cancels their own queued run -> 303 redirect, job=cancelled, audit row written, in-process flag set."""

    _import_and_lock_set(client_with_users, set_id="bench")
    # The lock flow leaves nikoleta logged in; switch back to mateo so the
    # run is "owned" by him for the cancel permission check.
    _logout(client_with_users)
    _login(client_with_users, "mateo")
    _insert_queued_run(run_id="run_test_cancel", set_id="bench", started_by_username="mateo")

    try:
        r = client_with_users.post(
            "/runs/run_test_cancel/cancel", follow_redirects=False
        )
        assert r.status_code == 303, r.text
        assert r.headers["location"] == "/runs/run_test_cancel"

        # Job is now cancelled, audit row exists, in-process flag was set so
        # the orchestrator thread (if any) would exit on its next check.
        s = db_module.SessionLocal()
        try:
            job = s.get(Job, "run_test_cancel")
            assert job.status == JobStatus.CANCELLED.value
            assert job.finished_at is not None
            from sqlalchemy import select as _select

            audit = s.execute(
                _select(AuditLog).where(
                    AuditLog.action == "run.cancelled",
                    AuditLog.target_id == "run_test_cancel",
                )
            ).scalar_one_or_none()
            assert audit is not None
        finally:
            s.close()
        assert is_cancellation_requested("run_test_cancel") is True
    finally:
        clear_cancellation("run_test_cancel")


def test_cancel_route_returns_204_for_htmx_request(client_with_users):
    """HTMX cancel button gets 204 + HX-Redirect so polling can re-target cleanly."""

    _import_and_lock_set(client_with_users, set_id="bench")
    _logout(client_with_users)
    _login(client_with_users, "mateo")
    _insert_queued_run(run_id="run_test_htmx", set_id="bench", started_by_username="mateo")

    try:
        r = client_with_users.post(
            "/runs/run_test_htmx/cancel",
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert r.status_code == 204
        assert r.headers["hx-redirect"] == "/runs/run_test_htmx"
    finally:
        clear_cancellation("run_test_htmx")


def test_cancel_route_forbidden_for_other_non_admin_users(client_with_users):
    """A reviewer who didn't start the run cannot cancel it; admin would be allowed."""

    _import_and_lock_set(client_with_users, set_id="bench")
    # Run started by mateo.
    _insert_queued_run(
        run_id="run_test_forbidden", set_id="bench", started_by_username="mateo"
    )
    # After _import_and_lock_set we are logged in as nikoleta (the reviewer).
    # She did NOT start the run and is not an admin -> 403.
    r = client_with_users.post(
        "/runs/run_test_forbidden/cancel", follow_redirects=False
    )
    assert r.status_code == 403

    # And the job status must NOT have been mutated.
    s = db_module.SessionLocal()
    try:
        job = s.get(Job, "run_test_forbidden")
        assert job.status == JobStatus.QUEUED.value
    finally:
        s.close()


def test_cancel_route_404_for_unknown_run(client_with_users):
    _login(client_with_users, "mateo")
    r = client_with_users.post("/runs/does_not_exist/cancel", follow_redirects=False)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/new + POST /runs/new — curated-catalog model picker
# ---------------------------------------------------------------------------
#
# These tests pin the UX cleanup from "feat(runs): catalog-backed model
# dropdown with provider grouping". The new form:
#   - renders a <select multiple name="models"> with one <optgroup> per
#     provider group
#   - validates submitted ids against ``MODEL_CATALOG``
#   - rejects ids whose ``requires_env`` is missing (e.g. openrouter ids
#     when ``OPENROUTER_API_KEY`` is unset)
#   - falls back to ``default_catalog_ids`` when the user submits nothing


def _login_mateo(client: TestClient) -> None:
    _login(client, "mateo")


@pytest.fixture
def no_openrouter_key(monkeypatch):
    """Force the catalog into "OpenAI-direct only" mode for the duration of
    a test by clearing ``OPENROUTER_API_KEY`` and rebuilding ``MODEL_CATALOG``
    so ``is_default`` flips back to the OpenAI preset."""

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import importlib

    from src.adapters import registry as reg

    importlib.reload(reg)
    # The route module imported these symbols at module load time, so
    # rebinding them on the route module is what actually changes route
    # behavior for the test.
    from src.web.routes import runs as runs_route

    runs_route.MODEL_CATALOG = reg.MODEL_CATALOG
    runs_route.DEFAULT_MODELS = reg.DEFAULT_MODELS
    runs_route.catalog_by_id = reg.catalog_by_id
    runs_route.catalog_grouped = reg.catalog_grouped
    runs_route.default_catalog_ids = reg.default_catalog_ids
    runs_route.group_is_available = reg.group_is_available
    yield
    importlib.reload(reg)
    runs_route.MODEL_CATALOG = reg.MODEL_CATALOG
    runs_route.DEFAULT_MODELS = reg.DEFAULT_MODELS
    runs_route.catalog_by_id = reg.catalog_by_id
    runs_route.catalog_grouped = reg.catalog_grouped
    runs_route.default_catalog_ids = reg.default_catalog_ids
    runs_route.group_is_available = reg.group_is_available


def test_new_run_form_renders_catalog_grouped_by_provider(client_with_users):
    """GET /runs/new must render the curated catalog as a <select multiple>
    with both provider <optgroup>s and the expected option ids."""

    _import_and_lock_set(client_with_users, set_id="bench")
    _logout(client_with_users)
    _login_mateo(client_with_users)

    r = client_with_users.get("/runs/new")
    assert r.status_code == 200
    body = r.text

    # Native multi-select replaces the old textarea / per-model switches.
    assert 'name="models"' in body
    assert "multiple" in body
    assert 'name="model_ids_csv"' not in body, (
        "old free-form textarea should be gone now that the picker is catalog-backed"
    )

    # Both provider groups render as <optgroup>s.
    assert 'label="OpenAI direct"' in body
    assert "OpenRouter cross-provider" in body  # label may have a suffix when disabled

    # Sample of expected option ids — one per provider group.
    assert 'value="openai:gpt-5.5"' in body
    assert 'value="openrouter:anthropic/claude-sonnet-4.5"' in body


def test_new_run_rejects_unknown_model_id(client_with_users):
    """POST /runs/new with a bogus model id must re-render the form with a
    flash error (400) instead of trying to launch the run."""

    _import_and_lock_set(client_with_users, set_id="bench")
    _logout(client_with_users)
    _login_mateo(client_with_users)

    r = client_with_users.post(
        "/runs/new",
        data={"set_id": "bench", "models": ["openai:bogus"], "notes": ""},
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    # The form re-renders with the error visible to the user.
    assert "Unknown model id" in r.text
    assert "openai:bogus" in r.text


def test_new_run_rejects_openrouter_when_no_key_set(
    client_with_users, no_openrouter_key
):
    """Submitting an OpenRouter model id must be rejected when
    ``OPENROUTER_API_KEY`` is not configured — runs would just fail at the
    first model call otherwise, with a much less helpful error."""

    _import_and_lock_set(client_with_users, set_id="bench")
    _logout(client_with_users)
    _login_mateo(client_with_users)

    r = client_with_users.post(
        "/runs/new",
        data={
            "set_id": "bench",
            "models": ["openrouter:anthropic/claude-sonnet-4.5"],
            "notes": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400, r.text
    assert "OPENROUTER_API_KEY" in r.text


def test_new_run_falls_back_to_defaults_when_models_empty(
    client_with_users, no_openrouter_key, monkeypatch
):
    """If the user submits the form with no models selected, the route must
    fall back to the default preset rather than 400'ing on an empty list."""

    _import_and_lock_set(client_with_users, set_id="bench")
    _logout(client_with_users)
    _login_mateo(client_with_users)

    # Stub out the background orchestrator: it would otherwise try to call
    # the real OpenAI API on the (in-memory) default preset.
    from src.web.routes import runs as runs_route

    captured: dict = {}

    def _fake_bg(run_id: str):
        captured["run_id"] = run_id

        class _T:
            pass

        return _T()

    monkeypatch.setattr(runs_route, "run_in_background", _fake_bg)

    r = client_with_users.post(
        "/runs/new",
        data={"set_id": "bench", "notes": ""},
        follow_redirects=False,
    )
    # No ``models`` field at all -> defaults preset -> 303 to the run page.
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("/runs/run_")

    # And the job's payload was seeded with the default OpenAI preset (no
    # OpenRouter key in this test) — exactly the 4-model preset.
    s = db_module.SessionLocal()
    try:
        run_id = r.headers["location"].rsplit("/", 1)[-1]
        job = s.get(Job, run_id)
        assert job is not None
        assert job.payload_json["model_ids"] == [
            "openai:gpt-5.5",
            "openai:gpt-5.4-mini",
            "openai:gpt-5-mini",
            "openai:o4-mini",
        ]
    finally:
        s.close()
