"""End-to-end test of the SQLAlchemy-backed pipeline.

Covers: import questions -> approve -> build prompt -> store_model_run +
store_answers_and_aggregates -> export_results returns the right rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmark.exporting import fetch_leaderboard_rows
from src.benchmark.importing import import_questions
from src.benchmark.pipeline import store_answers_and_aggregates, store_model_run
from src.benchmark.prompting import PromptingError, build_prompt_text
from src.benchmark.workflow import approve, lock, submit_review
from src.storage.models import QuestionSet, Run, SetStatus


SAMPLE_FILE = """C1. What is H2O?
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
def imports_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "answer_key"
    folder.mkdir()
    (folder / "Category_1_Chemistry.txt").write_text(SAMPLE_FILE, encoding="utf-8")
    return folder


def test_import_questions_creates_draft_set(session, imports_dir):
    summary = import_questions(
        session, source=imports_dir, set_id="benchmark_v1", title="Demo"
    )
    session.commit()

    assert summary.parsed_count == 2
    assert summary.inserted_count == 2
    assert summary.by_category == {"chemistry": 2}

    qs = session.get(QuestionSet, "benchmark_v1")
    assert qs is not None
    assert qs.status == SetStatus.DRAFT.value
    assert qs.title == "Demo"
    assert len(qs.questions) == 2


def test_review_workflow_blocks_self_approval(session, imports_dir, users):
    import_questions(
        session, source=imports_dir, set_id="benchmark_v1", author_id=users["author"].id
    )
    session.commit()

    submit_review(
        session,
        set_id="benchmark_v1",
        reviewer_id=users["reviewer"].id,
        actor_id=users["author"].id,
    )
    session.commit()

    # Reviewer (not the author) approves -> ok
    approve(
        session,
        set_id="benchmark_v1",
        reviewer_id=users["reviewer"].id,
        actor_id=users["reviewer"].id,
    )
    session.commit()

    lock(session, set_id="benchmark_v1", actor_id=users["reviewer"].id)
    session.commit()

    qs = session.get(QuestionSet, "benchmark_v1")
    assert qs.status == SetStatus.LOCKED.value


def test_self_approval_is_rejected(session, imports_dir, users):
    """Author cannot be assigned as their own reviewer."""

    import_questions(
        session, source=imports_dir, set_id="benchmark_v1", author_id=users["author"].id
    )
    session.commit()

    with pytest.raises(Exception):
        submit_review(
            session,
            set_id="benchmark_v1",
            reviewer_id=users["author"].id,
            actor_id=users["author"].id,
        )


def test_build_prompt_requires_approved(session, imports_dir):
    import_questions(session, source=imports_dir, set_id="benchmark_v1")
    session.commit()

    with pytest.raises(PromptingError):
        build_prompt_text(session, "benchmark_v1")


def test_full_run_persists_aggregate(session, imports_dir, users):
    import_questions(
        session, source=imports_dir, set_id="benchmark_v1", author_id=users["author"].id
    )
    submit_review(session, set_id="benchmark_v1", reviewer_id=users["reviewer"].id)
    approve(session, set_id="benchmark_v1", reviewer_id=users["reviewer"].id)
    lock(session, set_id="benchmark_v1")
    session.commit()

    run = Run(run_id="run_001", set_id="benchmark_v1")
    session.add(run)
    session.flush()

    mr = store_model_run(
        session,
        run_id="run_001",
        model_id="test:model",
        source="file",
        raw_text="C1: B\nC2: B\n",
    )
    store_answers_and_aggregates(
        session,
        model_run=mr,
        answer_key={"C1": "B", "C2": "B"},
        raw_text="C1: B\nC2: B\n",
    )
    session.commit()

    rows = fetch_leaderboard_rows(session, "run_001")
    assert len(rows) == 1
    row = rows[0]
    assert row["model_id"] == "test:model"
    assert row["total"] == 2  # both correct
    assert row["correct"] == 2
    assert row["wrong"] == 0
    assert row["chemistry"] == 2
