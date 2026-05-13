"""End-to-end tests for the Runs orchestration.

We mock the adapter layer so the test never hits a real API.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.adapters.base import ModelAdapter, ModelResult
from src.benchmark.importing import import_questions
from src.benchmark.runs import (
    RunError,
    clear_cancellation,
    create_run,
    execute_run,
    is_cancellation_requested,
    request_cancellation,
)
from src.benchmark.workflow import approve, lock, submit_review
from src.storage.models import (
    Aggregate,
    Job,
    JobStatus,
    ModelRun,
    QuestionSet,
    Run,
    SetStatus,
)


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

M1. What is 2+2?
A. 3
B. 4
C. 5
D. 22
E. 0
Correct answer: B
"""


class FakeAdapter(ModelAdapter):
    def __init__(self, model: str, *, answers: dict[str, str], fail: bool = False):
        self.model = model
        self._answers = answers
        self._fail = fail

    def id(self) -> str:
        return f"fake:{self.model}"

    def is_configured(self) -> bool:
        return True

    def run(self, prompt: str, **kwargs) -> ModelResult:
        if self._fail:
            raise RuntimeError(f"simulated failure for {self.model}")
        text = "\n".join(f"{qid}: {letter}" for qid, letter in self._answers.items())
        return ModelResult(
            model_id=self.id(),
            raw_text=text,
            meta={"provider": "fake", "model": self.model, "elapsed_ms": 1},
        )


@pytest.fixture
def locked_set_with_3_questions(session, tmp_path, users):
    folder = tmp_path / "k"
    folder.mkdir()
    (folder / "a.txt").write_text(SAMPLE, encoding="utf-8")

    import_questions(
        session,
        source=folder,
        set_id="benchmark_v1",
        author_id=users["author"].id,
        title="demo",
    )
    submit_review(session, set_id="benchmark_v1", reviewer_id=users["reviewer"].id)
    approve(session, set_id="benchmark_v1", reviewer_id=users["reviewer"].id)
    lock(session, set_id="benchmark_v1")
    session.commit()
    return "benchmark_v1"


def test_create_run_rejects_non_locked_set(session, users):
    session.add(QuestionSet(set_id="draft_set", status=SetStatus.DRAFT.value))
    session.commit()

    with pytest.raises(RunError):
        create_run(
            session,
            set_id="draft_set",
            model_ids=["fake:m"],
            started_by_id=users["author"].id,
        )


def test_create_run_rejects_empty_model_list(session, locked_set_with_3_questions, users):
    with pytest.raises(RunError):
        create_run(
            session,
            set_id=locked_set_with_3_questions,
            model_ids=[],
            started_by_id=users["author"].id,
        )


def test_execute_run_happy_path(session, locked_set_with_3_questions, users):
    perfect = FakeAdapter("good", answers={"C1": "B", "C2": "B", "M1": "B"})
    half = FakeAdapter("half", answers={"C1": "B", "C2": "A", "M1": "B"})

    def fake_get_adapter(model_id: str):
        return {"fake:good": perfect, "fake:half": half}[model_id]

    run, job = create_run(
        session,
        set_id=locked_set_with_3_questions,
        model_ids=["fake:good", "fake:half"],
        started_by_id=users["author"].id,
    )
    session.commit()

    with patch("src.benchmark.runs.get_adapter", side_effect=fake_get_adapter):
        finished = execute_run(session, run.run_id)

    assert finished.status == JobStatus.DONE.value
    assert finished.progress_done == 2
    assert finished.progress_total == 2

    model_runs = session.execute(select(ModelRun)).scalars().all()
    assert len(model_runs) == 2
    aggs = {a.model_run_id: a for a in session.execute(select(Aggregate)).scalars().all()}
    totals = sorted(a.total_score for a in aggs.values())
    # SCORE_WRONG = -10. "good" gets 3 correct -> +3. "half" gets 2 correct
    # (+2) and 1 wrong (-10) -> -8.
    assert totals == [-8, 3]


def test_execute_run_partial_failure(session, locked_set_with_3_questions, users):
    good = FakeAdapter("good", answers={"C1": "B", "C2": "B", "M1": "B"})
    broken = FakeAdapter("bad", answers={}, fail=True)

    def fake_get_adapter(model_id: str):
        return {"fake:good": good, "fake:bad": broken}[model_id]

    run, _ = create_run(
        session,
        set_id=locked_set_with_3_questions,
        model_ids=["fake:good", "fake:bad"],
        started_by_id=users["author"].id,
    )
    session.commit()

    with patch("src.benchmark.runs.get_adapter", side_effect=fake_get_adapter):
        finished = execute_run(session, run.run_id)

    # One model succeeded, one failed -> job done with partial message + error.
    assert finished.status == JobStatus.DONE.value
    assert finished.error
    assert "fake:bad" in finished.error


def test_execute_run_total_failure(session, locked_set_with_3_questions, users):
    broken = FakeAdapter("bad", answers={}, fail=True)

    def fake_get_adapter(model_id: str):
        return broken

    run, _ = create_run(
        session,
        set_id=locked_set_with_3_questions,
        model_ids=["fake:bad"],
        started_by_id=users["author"].id,
    )
    session.commit()

    with patch("src.benchmark.runs.get_adapter", side_effect=fake_get_adapter):
        finished = execute_run(session, run.run_id)

    assert finished.status == JobStatus.ERROR.value


def test_execute_run_exits_cleanly_on_cancellation(session, locked_set_with_3_questions, users):
    """Cancellation observed mid-run -> job ends in CANCELLED, completed model is preserved, remaining models are not invoked."""

    perfect = FakeAdapter("good", answers={"C1": "B", "C2": "B", "M1": "B"})
    not_called = FakeAdapter("never", answers={})

    call_log: list[str] = []

    def fake_get_adapter(model_id: str):
        call_log.append(model_id)
        if model_id == "fake:good":
            return perfect
        # Request cancellation as soon as the first model finishes, BEFORE
        # the second model is fetched. The orchestrator should observe the
        # flag at the top of its next loop iteration and bail out.
        return not_called

    run, _ = create_run(
        session,
        set_id=locked_set_with_3_questions,
        model_ids=["fake:good", "fake:never_runs", "fake:also_skipped"],
        started_by_id=users["author"].id,
    )
    session.commit()

    original_run_method = perfect.run

    def run_then_cancel(prompt: str, **kwargs):
        result = original_run_method(prompt, **kwargs)
        request_cancellation(run.run_id)
        return result

    perfect.run = run_then_cancel  # type: ignore[assignment]

    try:
        with patch("src.benchmark.runs.get_adapter", side_effect=fake_get_adapter):
            finished = execute_run(session, run.run_id)

        assert finished.status == JobStatus.CANCELLED.value
        assert finished.finished_at is not None
        assert "Cancelled" in (finished.message or "")
        # Only the first model was actually invoked.
        assert call_log == ["fake:good"]
        # And the cancellation flag is cleared at the end of execute_run so
        # the next run reusing the same id (we don't, but the contract holds)
        # would start fresh.
        assert is_cancellation_requested(run.run_id) is False
    finally:
        clear_cancellation(run.run_id)
