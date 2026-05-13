"""Anonymous template smoke tests.

These guard against regressions in the polished Jinja2 templates that
ship under ``src/web/templates/``. They were added after a Flask-style
``request.args.get(...)`` call shipped to production and 500'd every
logged-out hit of ``/auth/login`` (Starlette's ``Request`` does not
expose ``.args``; it's called ``query_params``).

Each test renders a logged-out page that the previous suite never
exercised. A 200 here means the template parsed, all Jinja globals
(``url_for``, ``csrf_token``, ``flashes``, ``current_user``) resolved,
and no Flask idiom snuck back in.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base  # noqa: E402
from src.web.app import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def test_get_login_renders_200_anonymous(client: TestClient) -> None:
    resp = client.get("/auth/login")
    assert resp.status_code == 200, resp.text[:500]
    # Design-system markers — confirms base.html + auth/login.html rendered.
    assert "Sign in" in resp.text
    assert "/static/css/app.css" in resp.text


def test_get_login_with_next_query_param_renders_200(client: TestClient) -> None:
    """Regression: ``request.args.get('next', '')`` 500'd here on Starlette."""

    resp = client.get("/auth/login?next=/questions")
    assert resp.status_code == 200, resp.text[:500]
    # The ``next`` value must be threaded into the hidden form input via
    # ``request.query_params.get('next', '')`` — verify it landed there.
    assert 'value="/questions"' in resp.text


def test_get_signup_renders_200_anonymous(client: TestClient) -> None:
    resp = client.get("/auth/signup")
    assert resp.status_code == 200, resp.text[:500]
    assert "Create" in resp.text


def test_get_forgot_renders_200_anonymous(client: TestClient) -> None:
    resp = client.get("/auth/forgot")
    assert resp.status_code == 200, resp.text[:500]


def test_get_reset_with_token_renders_200_anonymous(client: TestClient) -> None:
    """Regression: this template read ``request.args.get('token', '')``."""

    resp = client.get("/auth/reset?token=abc123")
    assert resp.status_code == 200, resp.text[:500]
    assert 'value="abc123"' in resp.text
