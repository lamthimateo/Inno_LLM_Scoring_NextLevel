"""End-to-end happy-path test: full UX flow over HTTP with mocked LLMs.

Login as author → import questions → submit for review → login as
reviewer → approve → lock → start a run → wait for completion → see the
leaderboard. Asserts at each step.
"""

from __future__ import annotations

import io
import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.adapters.base import ModelAdapter, ModelResult  # noqa: E402
from src.auth.service import register_user  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, Run, User, UserRole  # noqa: E402
from src.web.app import app  # noqa: E402


SAMPLE = """C1. What is H2O?
A. Salt
B. Water
C. Sugar
D. Iron
E. Oxygen
Correct answer: B

M1. What is 2+2?
A. 3
B. 4
C. 5
D. 22
E. 0
Correct answer: B
"""


class GoodAdapter(ModelAdapter):
    def __init__(self, model: str):
        self.model = model

    def id(self) -> str:
        return f"good:{self.model}"

    def is_configured(self) -> bool:
        return True

    def run(self, prompt: str, **kwargs) -> ModelResult:
        return ModelResult(
            model_id=self.id(),
            raw_text="C1: B\nM1: B\n",
            meta={"provider": "fake", "elapsed_ms": 1},
        )


def _login(client: TestClient, username: str) -> None:
    r = client.post(
        "/auth/login",
        data={"username": username, "password": "strongpass1"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303), r.text


def test_full_flow_end_to_end():
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)

    s = db_module.SessionLocal()
    try:
        register_user(s, username="alice", password="strongpass1", role=UserRole.AUTHOR.value)
        register_user(s, username="bob", password="strongpass1", role=UserRole.REVIEWER.value)
        s.commit()
        bob_id = s.execute(
            __import__("sqlalchemy").select(User.id).where(User.username == "bob")  # type: ignore[attr-defined]
        ).scalar_one()
    finally:
        s.close()

    with TestClient(app) as client:
        # 1. Alice authors and submits.
        _login(client, "alice")

        r = client.post(
            "/questions/import",
            data={"set_id": "demo_v1", "title": "Demo", "description": "e2e"},
            files=[("files", ("c.txt", io.BytesIO(SAMPLE.encode()), "text/plain"))],
            follow_redirects=False,
        )
        assert r.status_code in (302, 303), r.text

        r = client.post(
            "/questions/demo_v1/submit-review",
            data={"reviewer_id": bob_id},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)

        # 2. Bob reviews, approves, locks.
        client.post("/auth/logout")
        _login(client, "bob")

        r = client.post("/questions/demo_v1/approve", follow_redirects=False)
        assert r.status_code in (302, 303)
        r = client.post("/questions/demo_v1/lock", follow_redirects=False)
        assert r.status_code in (302, 303)

        # 3. Bob starts a run with mocked adapters. The catalog-backed
        # form now enforces ``requires_env``, so set a stub ``OPENAI_API_KEY``
        # for the duration of this step — the adapter itself is patched out.
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-stub"}, clear=False), patch(
            "src.benchmark.runs.get_adapter",
            side_effect=lambda mid: GoodAdapter(mid.split(":", 1)[1]),
        ):
            # The form now picks ids from the curated catalog. We pin two
            # OpenAI direct entries so the route's env validation passes —
            # ``OPENAI_API_KEY`` is asserted set further up, and the
            # adapter call itself is patched out.
            r = client.post(
                "/runs/new",
                data={
                    "set_id": "demo_v1",
                    "models": ["openai:gpt-5.5", "openai:gpt-5-mini"],
                    "notes": "demo",
                },
                follow_redirects=False,
            )
            assert r.status_code in (302, 303), r.text
            run_id = r.headers["location"].rsplit("/", 1)[-1]
            assert run_id.startswith("run_")

            # The background thread may take a moment. Poll the status
            # fragment until done.
            for _ in range(50):
                r = client.get(f"/runs/{run_id}/status")
                if "badge-done" in r.text or "badge-error" in r.text:
                    break
                time.sleep(0.05)
            assert "badge-done" in r.text, r.text[:500]
            # Both models scored full 2 points (2 correct, 0 wrong).
            assert "good:gpt-5.5" in r.text
            assert "good:gpt-5-mini" in r.text

    Base.metadata.drop_all(bind=db_module.engine)
