"""Integration tests for the auth HTTP routes using FastAPI's TestClient."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Tests use the same in-memory SQLite the conftest creates.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base  # noqa: E402
from src.web.app import app  # noqa: E402


@pytest.fixture
def client():
    """Yield a TestClient bound to a freshly-initialized in-memory DB."""

    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def test_home_redirects_to_login_when_anonymous(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].startswith("/auth/login")


def test_signup_creates_account_and_logs_in(client):
    resp = client.post(
        "/auth/signup",
        data={
            "username": "alice",
            "password": "strongpass1",
            "password_confirm": "strongpass1",
            "email": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.text
    assert resp.headers["location"].startswith("/?ok=")

    # Now / should render the home page instead of redirecting.
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200
    assert "Welcome back, alice" in resp2.text


def test_login_with_wrong_password_returns_401(client):
    client.post(
        "/auth/signup",
        data={
            "username": "alice",
            "password": "strongpass1",
            "password_confirm": "strongpass1",
            "email": "",
        },
    )
    # Clear session so we start anonymous again
    client.post("/auth/logout")

    resp = client.post(
        "/auth/login",
        data={"username": "alice", "password": "WRONG"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.text


def test_login_success_sets_session_cookie(client):
    client.post(
        "/auth/signup",
        data={
            "username": "alice",
            "password": "strongpass1",
            "password_confirm": "strongpass1",
            "email": "",
        },
    )
    client.post("/auth/logout")

    resp = client.post(
        "/auth/login",
        data={"username": "alice", "password": "strongpass1"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.cookies.get("inno_session") is not None


def test_change_password_requires_login(client):
    resp = client.get("/auth/change-password", follow_redirects=False)
    # require_login raises 303 redirect to /auth/login
    assert resp.status_code in (302, 303)
    assert "/auth/login" in resp.headers["location"]


def test_change_password_flow_when_logged_in(client):
    client.post(
        "/auth/signup",
        data={
            "username": "alice",
            "password": "strongpass1",
            "password_confirm": "strongpass1",
            "email": "",
        },
    )

    resp = client.post(
        "/auth/change-password",
        data={
            "current_password": "strongpass1",
            "new_password": "brandnew2",
            "new_password_confirm": "brandnew2",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert "ok=Password+updated" in resp.headers["location"]

    # Logout, then verify the new password works.
    client.post("/auth/logout")
    resp = client.post(
        "/auth/login",
        data={"username": "alice", "password": "brandnew2"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
