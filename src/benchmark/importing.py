"""Import benchmark question files into Postgres.

Reads every ``*.txt`` under a folder (typically ``imports/answer_key/``) and
populates the ``question_sets`` and ``questions`` tables. Returns a summary
that the web UI can show as an import preview.

The expected file format is::

    C1. <prompt text>
    A. <choice A>
    B. <choice B>
    ...
    E. <choice E>
    Correct answer: B

QID prefix maps to category:

    C = chemistry        E = emotions        M = math
    A = reasoning3d      N = no_knowledge    X = contradiction

Locked sets cannot be re-imported; use a new ``set_id`` such as
``benchmark_v2`` instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Question, QuestionSet, SetStatus


QID_RE = re.compile(r"^\s*([CEMANX]\d+)\.\s*(.*)$")
CHOICE_RE = re.compile(r"^\s*([A-E])\.\s*(.*)$")
ANSWER_RE = re.compile(
    r"^\s*(Correct answer|Correct|ANSWER)\s*:\s*([A-E])\s*$", re.IGNORECASE
)

CATEGORY_FROM_QID = {
    "C": "chemistry",
    "E": "emotions",
    "M": "math",
    "A": "reasoning3d",
    "N": "no_knowledge",
    "X": "contradiction",
}


class ImportError(ValueError):
    """Raised when an import cannot proceed (locked set, no files, etc.)."""


@dataclass
class ParsedQuestion:
    qid: str
    category: str
    prompt: str
    choices: list[dict[str, str]]
    correct_answer: Optional[str]
    source_file: str


@dataclass
class ImportSummary:
    set_id: str
    parsed_count: int = 0
    inserted_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)
    by_category: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.inserted_count > 0 and not any("error" in w.lower() for w in self.warnings)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _category_from_qid(qid: str) -> str:
    try:
        return CATEGORY_FROM_QID[qid[0]]
    except KeyError as exc:
        raise ImportError(f"Unknown QID prefix in {qid!r}; expected one of C/E/M/A/N/X") from exc


def parse_questions_from_text(text: str, source_name: str = "<inline>") -> list[ParsedQuestion]:
    """Parse a single benchmark text file's contents into ``ParsedQuestion``s."""

    lines = text.splitlines()
    out: list[ParsedQuestion] = []
    i = 0

    while i < len(lines):
        m_q = QID_RE.match(lines[i])
        if not m_q:
            i += 1
            continue

        qid = m_q.group(1)
        prompt = m_q.group(2).strip()
        choices: list[dict[str, str]] = []
        correct: Optional[str] = None

        j = i + 1
        while j < len(lines):
            if QID_RE.match(lines[j]):
                break
            m_c = CHOICE_RE.match(lines[j])
            if m_c:
                choices.append({"label": m_c.group(1), "text": m_c.group(2).strip()})
                j += 1
                continue
            m_a = ANSWER_RE.match(lines[j])
            if m_a:
                correct = m_a.group(2).upper()
                j += 1
                continue
            j += 1

        if len(choices) >= 5:
            out.append(
                ParsedQuestion(
                    qid=qid,
                    category=_category_from_qid(qid),
                    prompt=prompt,
                    choices=choices,
                    correct_answer=correct,
                    source_file=source_name,
                )
            )
        i = j

    return out


def parse_questions_from_folder(folder: str | Path) -> list[ParsedQuestion]:
    """Parse every ``*.txt`` under ``folder`` and return the union."""

    folder = Path(folder)
    out: list[ParsedQuestion] = []
    for fp in sorted(folder.glob("*.txt")):
        out.extend(parse_questions_from_text(fp.read_text(encoding="utf-8"), fp.name))
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def import_questions(
    session: Session,
    *,
    source: str | Path,
    set_id: str,
    author_id: Optional[int] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> ImportSummary:
    """Import a folder of benchmark text files into ``question_sets`` + ``questions``.

    Creates the set as ``draft`` if it doesn't exist. Replaces existing
    questions in the set unless it's already ``locked`` (raises in that case).
    """

    existing = session.get(QuestionSet, set_id)
    if existing and existing.status == SetStatus.LOCKED.value:
        raise ImportError(
            f"Set {set_id!r} is locked. Use a new set_id (e.g. {set_id}_v2)."
        )

    parsed = parse_questions_from_folder(source)
    if not parsed:
        raise ImportError(
            f"No questions parsed from {source}. "
            "Files must contain QID lines (e.g. 'C1. ...') with 5 choices "
            "and a 'Correct answer: X' line."
        )

    summary = ImportSummary(set_id=set_id, parsed_count=len(parsed))

    if existing is None:
        existing = QuestionSet(
            set_id=set_id,
            status=SetStatus.DRAFT.value,
            author_id=author_id,
            title=title,
            description=description,
        )
        session.add(existing)
    else:
        existing.status = SetStatus.DRAFT.value
        existing.author_id = author_id if author_id is not None else existing.author_id
        existing.reviewer_id = None
        if title is not None:
            existing.title = title
        if description is not None:
            existing.description = description

    session.flush()

    # Clear existing questions to support re-imports cleanly. Cascade rules
    # handle ``question_versions`` referencing them.
    session.execute(
        Question.__table__.delete().where(Question.set_id == set_id)
    )
    session.flush()

    seen_qids: set[str] = set()
    for q in parsed:
        if q.qid in seen_qids:
            summary.warnings.append(f"duplicate QID {q.qid} in {q.source_file}; skipped")
            summary.skipped_count += 1
            continue
        if q.correct_answer is None:
            summary.warnings.append(
                f"{q.qid} ({q.source_file}) has no 'Correct answer: X' line; imported but unscored"
            )

        session.add(
            Question(
                qid=q.qid,
                set_id=set_id,
                category=q.category,
                prompt=q.prompt,
                choices_json=q.choices,
                correct_answer=q.correct_answer,
                scoring_rule="mcq_v1",
                version=1,
            )
        )
        seen_qids.add(q.qid)
        summary.inserted_count += 1
        summary.by_category[q.category] = summary.by_category.get(q.category, 0) + 1

    session.flush()
    return summary


def load_answer_key(session: Session, set_id: str) -> dict[str, str]:
    """Return ``{qid: correct_answer}`` for the given set."""

    rows = session.execute(
        select(Question.qid, Question.correct_answer).where(Question.set_id == set_id)
    ).all()
    return {qid: correct for qid, correct in rows if correct is not None}
