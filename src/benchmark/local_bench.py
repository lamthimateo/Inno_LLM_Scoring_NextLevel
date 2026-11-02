"""Time and score locally installed models on N questions of a locked set.

Backs ``scripts/bench_local.py``. It answers "which local models are usable
on this machine, and how fast?" with *measured* numbers only: every figure
in the output comes from a real call made during the run.

For each model it sends one prompt built from the first N questions of the
set (the exact prompt cloud runs use, see :mod:`src.benchmark.prompting`),
times the call, and scores the reply with the normal parser and scoring
rules. An optional warm-up request loads the model first, so the timed call
does not include the one-off load time.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from sqlalchemy.orm import Session

from src.adapters.base import ModelAdapter
from src.adapters.registry import get_adapter
from src.benchmark.prompting import build_prompt_text, list_prompt_questions
from src.evaluator.parser_mcq import parse_model_output
from src.evaluator.scoring import score_answers
from src.storage.models import QuestionSet, SetStatus

WARMUP_PROMPT = "Reply with the single word: ready."


class BenchError(ValueError):
    """The benchmark cannot run (unknown or unlocked set, bad arguments)."""


@dataclass
class BenchRow:
    model_id: str
    questions: int = 0
    total_s: Optional[float] = None
    avg_s_per_question: Optional[float] = None
    score: Optional[int] = None
    correct: int = 0
    wrong: int = 0
    blank: int = 0
    notes: str = ""
    error: Optional[str] = None


def run_bench(
    session: Session,
    *,
    set_id: str,
    limit: int,
    model_ids: Sequence[str],
    warmup: bool = True,
    adapter_factory: Callable[[str], ModelAdapter] = get_adapter,
    clock: Callable[[], float] = time.perf_counter,
    progress: Optional[Callable[[str], None]] = None,
) -> list[BenchRow]:
    """Benchmark every model in ``model_ids``; one failing model never stops the rest."""

    if limit < 1:
        raise BenchError("Question count must be at least 1.")
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise BenchError(f"Unknown set_id: {set_id!r}")
    if qs.status != SetStatus.LOCKED.value:
        raise BenchError(
            f"Set {set_id!r} is {qs.status!r}; only locked sets can be benchmarked."
        )

    questions = list_prompt_questions(session, set_id, limit=limit)
    prompt = build_prompt_text(session, set_id, limit=limit)
    answer_key = {q.qid: q.correct_answer for q in questions if q.correct_answer}
    say = progress or (lambda _msg: None)

    rows: list[BenchRow] = []
    for model_id in model_ids:
        row = BenchRow(model_id=model_id, questions=len(questions))
        try:
            adapter = adapter_factory(model_id)
            if warmup:
                say(f"{model_id}: warming up (loading the model)…")
                adapter.run(WARMUP_PROMPT, max_output_tokens=8)
            say(f"{model_id}: answering {len(questions)} questions…")
            started = clock()
            result = adapter.run(prompt)
            elapsed = clock() - started
        except Exception as exc:  # report and continue with the next model
            row.error = " ".join(str(exc).split()) or exc.__class__.__name__
            rows.append(row)
            continue

        parsed, _violations = parse_model_output(result.raw_text)
        per_question, _per_category = score_answers(answer_key, parsed)
        for qid, points in per_question.items():
            if parsed.get(qid) is None:
                row.blank += 1
            elif points > 0:
                row.correct += 1
            else:
                row.wrong += 1
        row.score = sum(per_question.values())
        row.total_s = elapsed
        row.avg_s_per_question = elapsed / len(questions)

        notes = []
        if result.meta.get("empty_response"):
            notes.append("empty reply")
        if (result.meta.get("ollama") or {}).get("context_truncated_suspected"):
            notes.append("context cut off (suspected)")
        row.notes = ", ".join(notes)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def machine_description() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"


def format_markdown(
    rows: Sequence[BenchRow],
    *,
    set_id: str,
    questions: int,
    base_url: str,
    machine_label: Optional[str] = None,
    warmup: bool = True,
    when: Optional[datetime] = None,
) -> str:
    when = when or datetime.now(timezone.utc)
    lines = [
        f"### Local model benchmark — {when.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"- Machine: {machine_label + ' · ' if machine_label else ''}{machine_description()}",
        f"- Ollama: {base_url}",
        f"- Set: `{set_id}`, first {questions} question{'s' if questions != 1 else ''}",
        f"- Warm-up request before timing: {'yes (not included in the times)' if warmup else 'no (first call includes model load)'}",
        "- Scoring: +1 correct, 0 blank, −10 wrong",
        "",
        "| Model | Questions | Total time (s) | Avg per question (s) | Score | Correct | Wrong | Blank | Notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        if row.error:
            lines.append(f"| {row.model_id} | {row.questions} | — | — | — | — | — | — | error: {row.error} |")
            continue
        lines.append(
            f"| {row.model_id} | {row.questions} | {row.total_s:.1f} | {row.avg_s_per_question:.2f} "
            f"| {row.score} | {row.correct} | {row.wrong} | {row.blank} | {row.notes} |"
        )
    return "\n".join(lines) + "\n"
