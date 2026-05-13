"""Question-set review workflow.

Implements the four state transitions:

    draft -> in_review -> approved -> locked

Enforcement rules (the "two-person review"):

- ``submit_review``  caller must be authenticated; assigns a reviewer.
- ``approve``        reviewer must NOT be the author; status must be ``in_review``.
- ``lock``           status must be ``approved``; once locked, no further edits.
- ``revert_to_draft`` reviewer can bounce back if quality is insufficient.

All transitions write an :class:`~src.storage.models.AuditLog` row.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.storage.models import AuditLog, QuestionSet, SetStatus


class WorkflowError(ValueError):
    """Raised on illegal state transitions or authorization violations."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_set(session: Session, set_id: str) -> QuestionSet:
    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise WorkflowError(f"Unknown set_id: {set_id!r}")
    return qs


def _audit(
    session: Session,
    *,
    actor_id: Optional[int],
    action: str,
    target_id: str,
    payload: Optional[dict] = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type="question_set",
            target_id=target_id,
            payload_json=payload,
        )
    )


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def submit_review(
    session: Session, *, set_id: str, reviewer_id: int, actor_id: Optional[int] = None
) -> QuestionSet:
    """Move a draft set into ``in_review`` and assign a reviewer.

    The reviewer must not be the author (enforced here AND at the DB level
    via the audit log so a misbehaving caller is still detectable).
    """

    qs = _get_set(session, set_id)
    if qs.status != SetStatus.DRAFT.value:
        raise WorkflowError(
            f"Cannot submit for review: set is {qs.status!r} (must be 'draft')"
        )
    if qs.author_id is not None and qs.author_id == reviewer_id:
        raise WorkflowError("Reviewer must be a different user than the author.")

    qs.status = SetStatus.IN_REVIEW.value
    qs.reviewer_id = reviewer_id
    _audit(
        session,
        actor_id=actor_id,
        action="submit_review",
        target_id=set_id,
        payload={"reviewer_id": reviewer_id},
    )
    session.flush()
    return qs


def approve(
    session: Session, *, set_id: str, reviewer_id: int, actor_id: Optional[int] = None
) -> QuestionSet:
    """Approve a set that is currently in review.

    Only the assigned reviewer may approve, and they must not be the author.
    """

    qs = _get_set(session, set_id)
    if qs.status != SetStatus.IN_REVIEW.value:
        raise WorkflowError(
            f"Cannot approve: set is {qs.status!r} (must be 'in_review')"
        )
    if qs.reviewer_id is None or qs.reviewer_id != reviewer_id:
        raise WorkflowError("Only the assigned reviewer may approve this set.")
    if qs.author_id is not None and qs.author_id == reviewer_id:
        raise WorkflowError("Reviewer cannot approve a set they authored.")

    qs.status = SetStatus.APPROVED.value
    _audit(
        session, actor_id=actor_id, action="approve", target_id=set_id,
    )
    session.flush()
    return qs


def lock(
    session: Session, *, set_id: str, actor_id: Optional[int] = None
) -> QuestionSet:
    """Lock an approved set so it cannot be edited again.

    Locked sets are the only kind that can be used for evaluation runs —
    this is the reproducibility guarantee.
    """

    qs = _get_set(session, set_id)
    if qs.status != SetStatus.APPROVED.value:
        raise WorkflowError(
            f"Cannot lock: set is {qs.status!r} (must be 'approved')"
        )

    qs.status = SetStatus.LOCKED.value
    _audit(session, actor_id=actor_id, action="lock", target_id=set_id)
    session.flush()
    return qs


def revert_to_draft(
    session: Session, *, set_id: str, reason: str = "", actor_id: Optional[int] = None
) -> QuestionSet:
    """Bounce a set back to draft (e.g. reviewer rejects)."""

    qs = _get_set(session, set_id)
    if qs.status == SetStatus.LOCKED.value:
        raise WorkflowError("Locked sets cannot be reverted. Create a new set instead.")

    qs.status = SetStatus.DRAFT.value
    qs.reviewer_id = None
    _audit(
        session,
        actor_id=actor_id,
        action="revert_to_draft",
        target_id=set_id,
        payload={"reason": reason} if reason else None,
    )
    session.flush()
    return qs
