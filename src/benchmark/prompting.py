"""Build the strict MCQ prompt sent to every model.

The prompt enforces a deterministic output shape (``QID: LETTER`` per line)
so the parser in :mod:`src.evaluator.parser_mcq` can score replies without
LLM-side variability. Only ``approved`` or ``locked`` sets may be used to
build a prompt — this keeps benchmark runs reproducible against a frozen
question set.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Question, QuestionSet, SetStatus


class PromptingError(ValueError):
    """Raised when the prompt cannot be built (unknown set, wrong status)."""


def list_prompt_questions(
    session: Session, set_id: str, *, limit: Optional[int] = None
) -> list[Question]:
    """Questions of an approved or locked set, in the order they are prompted.

    ``limit`` keeps only the first N (used by the local-model benchmark).
    """

    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise PromptingError(f"Unknown set_id: {set_id!r}")
    if qs.status not in (SetStatus.APPROVED.value, SetStatus.LOCKED.value):
        raise PromptingError(
            f"Set must be approved or locked to build a prompt (got {qs.status!r})."
        )
    if limit is not None and limit < 1:
        raise PromptingError("limit must be at least 1.")

    stmt = select(Question).where(Question.set_id == set_id).order_by(Question.qid)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def build_prompt_text(session: Session, set_id: str, *, limit: Optional[int] = None) -> str:
    questions = list_prompt_questions(session, set_id, limit=limit)

    header = (
        "You will answer a multiple-choice benchmark.\n\n"
        "RULES (STRICT):\n"
        "1) Output ONLY answers in the format: QID: LETTER\n"
        "2) One answer per line.\n"
        "3) Allowed letters: A, B, C, D, E only.\n"
        "4) No explanations, no extra text, no markdown.\n"
        "5) If you are unsure, leave it blank after the colon (example: C7: ).\n"
        "6) Answer every question ID shown.\n\n"
        "ANSWER TEMPLATE (fill letters):\n"
    )

    template_txt = "\n".join(f"{q.qid}: " for q in questions)

    body: list[str] = ["", "", "QUESTIONS:", ""]
    for q in questions:
        body.append(f"{q.qid}. {q.prompt}")
        for c in q.choices_json:
            body.append(f"{c['label']}. {c['text']}")
        body.append("")

    return header + template_txt + "\n".join(body)
