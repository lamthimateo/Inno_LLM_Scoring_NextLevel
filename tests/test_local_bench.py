"""Local-model benchmark: prompt limit, timing/scoring logic and the CLI wrapper.

Adapters are fakes and the clock is injected: no Ollama, no real timings.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.adapters import ollama_adapter as oa
from src.adapters.base import ModelAdapter, ModelResult
from src.benchmark import local_bench
from src.benchmark.importing import import_questions
from src.benchmark.local_bench import BenchError, BenchRow, WARMUP_PROMPT, format_markdown, run_bench
from src.benchmark.prompting import PromptingError, build_prompt_text, list_prompt_questions
from src.benchmark.workflow import approve, lock, submit_review
from src.storage.models import QuestionSet, SetStatus

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


@pytest.fixture
def locked_set(session, tmp_path, users):
    folder = tmp_path / "k"
    folder.mkdir()
    (folder / "a.txt").write_text(SAMPLE, encoding="utf-8")
    import_questions(session, source=folder, set_id="bench_v1", author_id=users["author"].id, title="demo")
    submit_review(session, set_id="bench_v1", reviewer_id=users["reviewer"].id)
    approve(session, set_id="bench_v1", reviewer_id=users["reviewer"].id)
    lock(session, set_id="bench_v1")
    session.commit()
    return "bench_v1"


class FakeLocal(ModelAdapter):
    def __init__(self, model_id, answers=None, *, meta=None, fail=None):
        self.model_id = model_id
        self.answers = answers or {}
        self.meta = meta or {}
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def id(self):
        return self.model_id

    def run(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.fail:
            raise self.fail
        text = "\n".join(f"{qid}: {letter}" for qid, letter in self.answers.items())
        return ModelResult(self.model_id, text, dict(self.meta))


def ticks(*values):
    it = iter(values)
    return lambda: next(it)


# ------------------------------------------------------------- prompt limiting


def test_prompt_can_be_limited_to_the_first_n_questions(session, locked_set):
    prompt = build_prompt_text(session, locked_set, limit=2)

    assert "C1: " in prompt and "C2: " in prompt
    assert "M1" not in prompt
    assert "M1" in build_prompt_text(session, locked_set)  # unlimited is unchanged


def test_listed_questions_follow_prompt_order(session, locked_set):
    assert [q.qid for q in list_prompt_questions(session, locked_set)] == ["C1", "C2", "M1"]
    assert [q.qid for q in list_prompt_questions(session, locked_set, limit=2)] == ["C1", "C2"]


def test_limit_must_be_positive(session, locked_set):
    with pytest.raises(PromptingError):
        build_prompt_text(session, locked_set, limit=0)


# ---------------------------------------------------------------- run_bench


def bench(session, adapters, **kwargs):
    kwargs.setdefault("limit", 2)
    kwargs.setdefault("set_id", "bench_v1")
    return run_bench(
        session,
        model_ids=list(adapters),
        adapter_factory=lambda model_id: adapters[model_id],
        **kwargs,
    )


def test_scores_with_the_normal_rules_and_times_the_call(session, locked_set):
    model = FakeLocal("ollama:a", {"C1": "B", "C2": "A"})  # right, wrong

    [row] = bench(session, {"ollama:a": model}, clock=ticks(100.0, 112.0))

    assert row.questions == 2
    assert row.total_s == 12.0
    assert row.avg_s_per_question == 6.0
    assert (row.correct, row.wrong, row.blank) == (1, 1, 0)
    assert row.score == 1 - 10
    assert row.error is None


def test_unanswered_questions_are_blank(session, locked_set):
    model = FakeLocal("ollama:a", {"C1": "B"})

    [row] = bench(session, {"ollama:a": model}, clock=ticks(0.0, 1.0))

    assert (row.correct, row.wrong, row.blank) == (1, 0, 1)
    assert row.score == 1


def test_only_the_first_n_questions_are_sent_and_scored(session, locked_set):
    model = FakeLocal("ollama:a", {"C1": "B", "C2": "B", "M1": "A"})  # M1 is out of range

    [row] = bench(session, {"ollama:a": model}, limit=2, warmup=False, clock=ticks(0.0, 2.0))

    assert "M1" not in model.calls[0][0]
    assert row.score == 2  # the wrong M1 answer is not counted


def test_a_warmup_request_loads_the_model_and_is_not_timed(session, locked_set):
    model = FakeLocal("ollama:a", {"C1": "B", "C2": "B"})
    stamps = []

    def clock():
        stamps.append(len(model.calls))  # how many calls had happened at each reading
        return float(len(stamps))

    bench(session, {"ollama:a": model}, clock=clock)

    assert model.calls[0] == (WARMUP_PROMPT, {"max_output_tokens": 8})
    assert "C1: " in model.calls[1][0]  # the real prompt
    assert stamps == [1, 2]  # both readings bracket only the real call


def test_warmup_can_be_skipped(session, locked_set):
    model = FakeLocal("ollama:a", {"C1": "B"})

    bench(session, {"ollama:a": model}, warmup=False, clock=ticks(0.0, 1.0))

    assert len(model.calls) == 1


def test_one_failing_model_does_not_stop_the_others(session, locked_set):
    adapters = {
        "ollama:down": FakeLocal("ollama:down", fail=RuntimeError("Ollama is not\nreachable")),
        "ollama:ok": FakeLocal("ollama:ok", {"C1": "B", "C2": "B"}),
    }

    down, ok = bench(session, adapters, clock=ticks(0.0, 3.0))

    assert down.error == "Ollama is not reachable"
    assert down.score is None and down.total_s is None
    assert ok.error is None and ok.score == 2


def test_notes_flag_empty_replies_and_suspected_truncation(session, locked_set):
    adapters = {
        "ollama:empty": FakeLocal("ollama:empty", {}, meta={"empty_response": True}),
        "ollama:cut": FakeLocal(
            "ollama:cut", {"C1": "B"}, meta={"ollama": {"context_truncated_suspected": True}}
        ),
    }

    empty, cut = bench(session, adapters, warmup=False, clock=ticks(0, 1, 2, 3))

    assert empty.notes == "empty reply"
    assert cut.notes == "context cut off (suspected)"


@pytest.mark.parametrize("limit", [0, -3])
def test_rejects_a_non_positive_question_count(session, locked_set, limit):
    with pytest.raises(BenchError):
        bench(session, {}, limit=limit)


def test_only_locked_sets_can_be_benchmarked(session, locked_set):
    qs = session.get(QuestionSet, locked_set)
    qs.status = SetStatus.APPROVED.value
    session.commit()

    with pytest.raises(BenchError, match="only locked sets"):
        bench(session, {})


def test_unknown_set_is_reported(session):
    with pytest.raises(BenchError, match="Unknown set_id"):
        bench(session, {}, set_id="nope")


# ----------------------------------------------------------------- markdown


def test_markdown_contains_only_the_measured_values():
    rows = [
        BenchRow("ollama:a", questions=10, total_s=12.34, avg_s_per_question=1.234, score=7,
                 correct=8, wrong=0, blank=2, notes=""),
        BenchRow("ollama:b", questions=10, error="Ollama is not reachable"),
    ]

    text = format_markdown(
        rows,
        set_id="bench_v1",
        questions=10,
        base_url="http://localhost:11434",
        machine_label="Mac M3, 16 GB",
        warmup=True,
        when=datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc),
    )

    assert "### Local model benchmark — 2026-11-03 09:30 UTC" in text
    assert "Machine: Mac M3, 16 GB · " in text
    assert "Set: `bench_v1`, first 10 questions" in text
    assert "Warm-up request before timing: yes" in text
    assert "| ollama:a | 10 | 12.3 | 1.23 | 7 | 8 | 0 | 2 |  |" in text
    assert "| ollama:b | 10 | — | — | — | — | — | — | error: Ollama is not reachable |" in text


def test_markdown_says_when_the_warmup_was_skipped():
    text = format_markdown([], set_id="s", questions=1, base_url="u", warmup=False)

    assert "first call includes model load" in text


# ----------------------------------------------------------------------- CLI


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parent.parent / "scripts" / "bench_local.py"
    spec = importlib.util.spec_from_file_location("bench_local_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def up(*names):
    return oa.Discovery("http://localhost:11434", True, tuple(oa.LocalModel(n) for n in names))


def test_cli_reports_an_unreachable_ollama(cli, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "discover_models", lambda *a, **k: oa.Discovery("http://x:1", False, error="Ollama is not reachable at http://x:1.")
    )

    code = cli.main(["--set-id", "bench_v1"])

    assert code == 1
    assert "not reachable" in capsys.readouterr().err


def test_cli_rejects_models_that_are_not_installed(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover_models", lambda *a, **k: up("llama3.1:8b"))

    code = cli.main(["--set-id", "bench_v1", "--models", "llama3.1:8b,ghost:1b"])

    err = capsys.readouterr().err
    assert code == 1
    assert "not installed in Ollama: ghost:1b" in err
    assert "installed: llama3.1:8b" in err


def test_cli_needs_at_least_one_installed_model(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover_models", lambda *a, **k: up())

    assert cli.main(["--set-id", "bench_v1"]) == 1
    assert "no models installed" in capsys.readouterr().err


def test_cli_prints_a_table_for_every_installed_model(cli, monkeypatch, session, locked_set, capsys):
    monkeypatch.setattr(cli, "discover_models", lambda *a, **k: up("a:1b", "b:2b"))
    fakes = {
        "ollama:a:1b": FakeLocal("ollama:a:1b", {"C1": "B", "C2": "B"}),
        "ollama:b:2b": FakeLocal("ollama:b:2b", {"C1": "A"}),
    }
    real_run_bench = local_bench.run_bench
    monkeypatch.setattr(
        cli,
        "run_bench",
        lambda *a, **kw: real_run_bench(*a, adapter_factory=lambda mid: fakes[mid], **kw),
    )

    code = cli.main(["--set-id", locked_set, "-n", "2", "--machine", "Test box", "--no-warmup"])

    out = capsys.readouterr()
    assert code == 0
    assert "| ollama:a:1b | 2 |" in out.out
    assert "| ollama:b:2b | 2 |" in out.out
    assert "Machine: Test box · " in out.out
    assert "first call includes model load" in out.out
    assert "answering 2 questions" in out.err  # progress goes to stderr


def test_cli_strips_an_ollama_prefix_from_model_names(cli, monkeypatch, session, locked_set, capsys):
    monkeypatch.setattr(cli, "discover_models", lambda *a, **k: up("a:1b"))
    seen = {}
    monkeypatch.setattr(
        cli, "run_bench", lambda *a, **kw: seen.update(ids=kw["model_ids"]) or []
    )

    cli.main(["--set-id", locked_set, "--models", "ollama:a:1b"])

    assert seen["ids"] == ["ollama:a:1b"]


def test_cli_explains_an_unlocked_set(cli, monkeypatch, session, locked_set, capsys):
    session.get(QuestionSet, locked_set).status = SetStatus.DRAFT.value
    session.commit()
    monkeypatch.setattr(cli, "discover_models", lambda *a, **k: up("a:1b"))

    code = cli.main(["--set-id", locked_set])

    assert code == 1
    assert "only locked sets" in capsys.readouterr().err
