"""Admin page: configured Ollama address, installed models, provider key status."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.adapters import ollama_adapter as oa  # noqa: E402
from src.auth.service import register_user  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, UserRole  # noqa: E402
from src.web.app import app  # noqa: E402


@pytest.fixture
def client():
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)
    s = db_module.SessionLocal()
    try:
        register_user(s, username="root", password="strongpass1", role=UserRole.ADMIN.value)
        register_user(s, username="mateo", password="strongpass1", role=UserRole.AUTHOR.value)
        s.commit()
    finally:
        s.close()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def login(client: TestClient, username: str) -> None:
    client.post("/auth/logout")
    r = client.post(
        "/auth/login",
        data={"username": username, "password": "strongpass1"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)


def serve(monkeypatch, *models: oa.LocalModel, reachable: bool = True, base_url="http://ollama:11434"):
    discovery = oa.Discovery(
        base_url=base_url,
        reachable=reachable,
        models=tuple(models),
        error=None if reachable else f"Ollama is not reachable at {base_url}.",
    )
    monkeypatch.setattr(oa, "discover_models", lambda *a, **k: discovery)


LLAMA = oa.LocalModel(
    "llama3.1:8b",
    size_bytes=4_920_753_328,
    parameter_size="8.0B",
    quantization="Q4_0",
    family="llama",
)


# ---------------------------------------------------------------- access rules


def test_anonymous_visitors_are_sent_to_login(client):
    r = client.get("/admin", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"].startswith("/auth/login")


def test_non_admins_are_forbidden(client):
    login(client, "mateo")

    assert client.get("/admin").status_code == 403


def test_admins_can_open_the_page(client, monkeypatch):
    serve(monkeypatch, LLAMA)
    login(client, "root")

    assert client.get("/admin").status_code == 200


def test_admin_link_is_only_in_the_nav_for_admins(client):
    login(client, "mateo")
    assert 'href="/admin"' not in client.get("/runs").text

    login(client, "root")
    assert 'href="/admin"' in client.get("/runs").text


# -------------------------------------------------------------------- content


def test_shows_the_configured_address_and_installed_models(client, monkeypatch):
    serve(monkeypatch, LLAMA, base_url="http://host.docker.internal:11434")
    login(client, "root")

    html = client.get("/admin").text

    assert "http://host.docker.internal:11434" in html
    assert "Reachable" in html
    assert "ollama:llama3.1:8b" in html
    assert "8.0B" in html
    assert "Q4_0" in html
    assert "4.9 GB" in html


def test_explains_an_unreachable_server_without_failing(client):
    login(client, "root")  # conftest stub: Ollama not reachable

    r = client.get("/admin")

    assert r.status_code == 200
    assert "Not reachable" in r.text
    assert "Ollama is not reachable at http://ollama.test:11434." in r.text
    assert "host.docker.internal" in r.text  # the how-to-fix hint


def test_a_running_server_without_models_says_so(client, monkeypatch):
    serve(monkeypatch)  # reachable, empty
    login(client, "root")

    html = client.get("/admin").text

    assert "no models installed" in html
    assert "ollama pull" in html


def test_page_asks_ollama_fresh_instead_of_using_the_cache(client, monkeypatch):
    seen = []

    def fake(*args, **kwargs):
        seen.append(kwargs.get("use_cache", True))
        return oa.Discovery("http://ollama:11434", True, ())

    monkeypatch.setattr(oa, "discover_models", fake)
    login(client, "root")

    client.get("/admin")

    assert seen == [False]


def test_provider_table_shows_key_names_and_status_but_never_values(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    login(client, "root")

    html = client.get("/admin").text

    assert "OPENAI_API_KEY" in html
    assert "Configured" in html
    assert "sk-super-secret-value" not in html
