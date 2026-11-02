"""Local (Ollama) models in the new-run dialog and in run validation.

Discovery is always faked: the autouse conftest fixture makes Ollama
"unreachable", and tests that need local models install their own answer.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.adapters import ollama_adapter as oa  # noqa: E402
from src.auth.service import register_user  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, UserRole  # noqa: E402
from src.web.app import app  # noqa: E402
from src.web.routes.runs import _validate_selected_models  # noqa: E402


@pytest.fixture
def client():
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)
    s = db_module.SessionLocal()
    try:
        register_user(s, username="mateo", password="strongpass1", role=UserRole.AUTHOR.value)
        s.commit()
    finally:
        s.close()
    with TestClient(app) as c:
        r = c.post(
            "/auth/login",
            data={"username": "mateo", "password": "strongpass1"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def serve_models(monkeypatch, *names: str, reachable: bool = True) -> None:
    discovery = oa.Discovery(
        base_url="http://localhost:11434",
        reachable=reachable,
        models=tuple(oa.LocalModel(n, size_bytes=4_700_000_000) for n in names),
    )
    monkeypatch.setattr(oa, "discover_models", lambda *a, **k: discovery)


def tag(html: str, pattern: str) -> str:
    match = re.search(pattern, html)
    assert match, f"no match for {pattern!r}"
    return match.group(0)


# ------------------------------------------------------------------ the picker


def test_installed_local_models_appear_in_their_own_section(client, monkeypatch):
    serve_models(monkeypatch, "llama3.1:8b", "qwen2.5:7b")

    html = client.get("/runs").text

    group = tag(html, r'<optgroup label="Local \(Ollama\)"[^>]*>')
    assert "disabled" not in group
    assert 'value="ollama:llama3.1:8b"' in html
    assert 'value="ollama:qwen2.5:7b"' in html
    assert "data-local-models-note" not in html


def test_local_models_are_never_preselected(client, monkeypatch):
    serve_models(monkeypatch, "llama3.1:8b")

    html = client.get("/runs").text

    option = tag(html, r'<option value="ollama:llama3.1:8b"[^>]*>')
    assert "selected" not in option


def test_cloud_models_stay_next_to_the_local_section(client, monkeypatch):
    serve_models(monkeypatch, "llama3.1:8b")

    html = client.get("/runs").text

    assert '<optgroup label="OpenAI direct"' in html
    assert '<optgroup label="Local (Ollama)"' in html


def test_section_is_hidden_and_a_message_shown_when_ollama_is_unreachable(client):
    html = client.get("/runs").text  # default stub: not reachable

    assert "Local (Ollama)" not in html
    assert "ollama:" not in html
    assert "Local models unavailable" in html
    assert "Ollama is not reachable at http://ollama.test:11434." in html
    assert "OLLAMA_BASE_URL" in html


def test_page_still_works_and_lists_cloud_models_when_ollama_is_down(client):
    response = client.get("/runs")

    assert response.status_code == 200
    assert '<optgroup label="OpenAI direct"' in response.text


def test_running_ollama_without_models_hides_the_section_and_says_why(client, monkeypatch):
    serve_models(monkeypatch)  # reachable, nothing installed

    html = client.get("/runs").text

    assert "Local (Ollama)" not in html
    assert "has no models installed" in html
    assert "ollama pull" in html
    assert "Local models unavailable" not in html


# ------------------------------------------------------------------ validation


def test_a_discovered_local_model_is_accepted(monkeypatch):
    serve_models(monkeypatch, "llama3.1:8b")

    ids, error = _validate_selected_models(["ollama:llama3.1:8b"])

    assert error is None
    assert ids == ["ollama:llama3.1:8b"]


def test_an_unknown_local_model_is_rejected_while_ollama_is_up(monkeypatch):
    serve_models(monkeypatch, "llama3.1:8b")

    ids, error = _validate_selected_models(["ollama:not-installed:1b"])

    assert ids == []
    assert "Unknown model id" in error


def test_a_local_model_is_explained_when_ollama_went_away(monkeypatch):
    serve_models(monkeypatch, reachable=False)

    ids, error = _validate_selected_models(["ollama:llama3.1:8b"])

    assert ids == []
    assert "can't be used" in error
    assert "Start Ollama or choose a cloud model" in error


def test_submitting_a_local_model_while_ollama_is_down_returns_a_friendly_error(client):
    response = client.post(
        "/runs/new",
        data={"set_id": "whatever", "models": ["ollama:llama3.1:8b"]},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "not reachable" in response.text
