"""Read-side query helpers for the Questions tab.

Kept separate from the write-side modules (``importing``, ``workflow``) so
the UI layer can compose lookups without dragging in mutation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import Question, QuestionSet, SetStatus, User


@dataclass
class SetListRow:
    set_id: str
    title: Optional[str]
    description: Optional[str]
    status: str
    author_username: Optional[str]
    reviewer_username: Optional[str]
    question_count: int
    updated_at: str

    @property
    def author_or_dash(self) -> str:
        return self.author_username or "—"

    @property
    def reviewer_or_dash(self) -> str:
        return self.reviewer_username or "—"


def list_sets(
    session: Session,
    *,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[SetListRow]:
    """Return all sets matching the (optional) filters, newest first."""

    AuthorUser = User.__table__.alias("author_u")
    ReviewerUser = User.__table__.alias("reviewer_u")

    stmt = (
        select(
            QuestionSet.set_id,
            QuestionSet.title,
            QuestionSet.description,
            QuestionSet.status,
            AuthorUser.c.username.label("author_username"),
            ReviewerUser.c.username.label("reviewer_username"),
            func.count(Question.qid).label("question_count"),
            QuestionSet.updated_at,
        )
        .select_from(QuestionSet)
        .outerjoin(AuthorUser, AuthorUser.c.id == QuestionSet.author_id)
        .outerjoin(ReviewerUser, ReviewerUser.c.id == QuestionSet.reviewer_id)
        .outerjoin(Question, Question.set_id == QuestionSet.set_id)
        .group_by(
            QuestionSet.set_id,
            QuestionSet.title,
            QuestionSet.description,
            QuestionSet.status,
            AuthorUser.c.username,
            ReviewerUser.c.username,
            QuestionSet.updated_at,
        )
        .order_by(QuestionSet.updated_at.desc())
    )

    if status:
        stmt = stmt.where(QuestionSet.status == status)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            (func.lower(QuestionSet.set_id).like(like))
            | (func.lower(QuestionSet.title).like(like))
            | (func.lower(QuestionSet.description).like(like))
        )

    rows: list[SetListRow] = []
    for r in session.execute(stmt).all():
        rows.append(
            SetListRow(
                set_id=r.set_id,
                title=r.title,
                description=r.description,
                status=r.status,
                author_username=r.author_username,
                reviewer_username=r.reviewer_username,
                question_count=r.question_count,
                updated_at=str(r.updated_at) if r.updated_at else "",
            )
        )
    return rows


def count_by_status(session: Session) -> dict[str, int]:
    """Return ``{status: count}`` for every known status (zero if absent)."""

    rows = session.execute(
        select(QuestionSet.status, func.count()).group_by(QuestionSet.status)
    ).all()
    counts = {s.value: 0 for s in SetStatus}
    counts["total"] = 0
    for status, n in rows:
        counts[status] = n
        counts["total"] += n
    return counts


def get_set_with_questions(
    session: Session, set_id: str
) -> Optional[tuple[QuestionSet, list[Question]]]:
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        return None
    questions = session.execute(
        select(Question).where(Question.set_id == set_id).order_by(Question.qid)
    ).scalars().all()
    return qs, list(questions)


def get_question(session: Session, *, set_id: str, qid: str) -> Optional[Question]:
    return session.execute(
        select(Question).where(Question.set_id == set_id, Question.qid == qid)
    ).scalar_one_or_none()


def list_question_versions(session: Session, *, set_id: str, qid: str):
    from src.storage.models import QuestionVersion

    return session.execute(
        select(QuestionVersion)
        .where(QuestionVersion.set_id == set_id, QuestionVersion.qid == qid)
        .order_by(QuestionVersion.version.desc())
    ).scalars().all()
