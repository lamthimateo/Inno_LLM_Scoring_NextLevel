"""The question edit form must post to the route that actually saves it."""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["SESSION_SECRET"] = "test-secret-please-rotate"

from src.auth.service import register_user  # noqa: E402
from src.benchmark.importing import import_questions  # noqa: E402
from src.storage import db as db_module  # noqa: E402
from src.storage.models import Base, Question, UserRole  # noqa: E402
from src.web.app import app  # noqa: E402

SAMPLE = """C1. What is H2O?
A. Salt
B. Water
C. Sugar
D. Iron
E. Oxygen
Correct answer: B
"""


@pytest.fixture
def client(tmp_path):
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)
    s = db_module.SessionLocal()
    try:
        alice = register_user(s, username="alice", password="strongpass1", role=UserRole.AUTHOR.value)
        folder = tmp_path / "k"
        folder.mkdir()
        (folder / "a.txt").write_text(SAMPLE, encoding="utf-8")
        import_questions(s, source=folder, set_id="edit_v1", author_id=alice.id, title="demo")
        s.commit()
    finally:
        s.close()
    with TestClient(app) as c:
        r = c.post("/auth/login", data={"username": "alice", "password": "strongpass1"}, follow_redirects=False)
        assert r.status_code in (302, 303)
        yield c
    Base.metadata.drop_all(bind=db_module.engine)


def test_the_edit_form_posts_to_the_save_route_and_saves(client):
    page = client.get("/questions/edit_v1/C1")
    assert page.status_code == 200

    # the page also has the sidebar's logout form, so pick the one for this question
    action = re.search(r'<form[^>]*method="post"[^>]*action="([^"]*/C1[^"]*)"', page.text).group(1)
    assert action == "/questions/edit_v1/C1/edit"

    response = client.post(
        action,
        data={
            "prompt": "What does H2O stand for?",
            "choice_a": "Salt",
            "choice_b": "Water",
            "choice_c": "Sugar",
            "choice_d": "Iron",
            "choice_e": "Oxygen",
            "correct_answer": "B",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    s = db_module.SessionLocal()
    try:
        assert s.get(Question, ("C1", "edit_v1")).prompt == "What does H2O stand for?"
    finally:
        s.close()
