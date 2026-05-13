"""SQLAlchemy ORM models — the entire target schema.

All tables (existing + new for v0.2.0) live here. Alembic auto-generates
the initial migration from this metadata. Cross-dialect: works on Postgres
(production) and SQLite (tests) without changes.

Tables:

- ``users``               authn + role assignment
- ``audit_log``           every state-changing user action
- ``question_sets``       benchmark sets w/ review workflow + author/reviewer FKs
- ``questions``           current (latest) version of each question
- ``question_versions``   historical revisions for diff view
- ``runs``                one evaluation run against a locked set
- ``model_runs``          raw output captured per model per run
- ``answers``             per-question scoring inside a model_run
- ``aggregates``          per-model_run leaderboard totals
- ``jobs``                background job persistence (RQ-backed)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Enum-like string values (kept as Python Enums for type safety; stored as
# plain strings in the DB so the schema is portable across dialects).
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    ADMIN = "admin"
    AUTHOR = "author"
    REVIEWER = "reviewer"


class SetStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    LOCKED = "locked"


class ModelRunSource(str, Enum):
    FILE = "file"
    API = "api"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class Base(DeclarativeBase):
    """Common declarative base for every ORM model."""


# ---------------------------------------------------------------------------
# Users + audit log
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.AUTHOR.value,
        server_default=UserRole.AUTHOR.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','author','reviewer')",
            name="ck_users_role_valid",
        ),
    )


class AuditLog(Base):
    """Append-only audit trail of state-changing actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Benchmark content
# ---------------------------------------------------------------------------


class QuestionSet(Base):
    __tablename__ = "question_sets"

    set_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SetStatus.DRAFT.value,
        server_default=SetStatus.DRAFT.value,
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="set", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="set")
    author: Mapped[Optional["User"]] = relationship(foreign_keys=[author_id])
    reviewer: Mapped[Optional["User"]] = relationship(foreign_keys=[reviewer_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','in_review','approved','locked')",
            name="ck_qset_status_valid",
        ),
    )


class Question(Base):
    """Current version of a question. Older versions live in ``question_versions``."""

    __tablename__ = "questions"

    qid: Mapped[str] = mapped_column(String(20), primary_key=True)
    set_id: Mapped[str] = mapped_column(
        ForeignKey("question_sets.set_id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    choices_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    correct_answer: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    scoring_rule: Mapped[str] = mapped_column(String(40), nullable=False, default="mcq_v1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    set: Mapped["QuestionSet"] = relationship(back_populates="questions")


class QuestionVersion(Base):
    """Append-only snapshot of a question at a particular version.

    Used by the edit/diff view to show how a question evolved during review.
    """

    __tablename__ = "question_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qid: Mapped[str] = mapped_column(String(20), nullable=False)
    set_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    choices_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    correct_answer: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    scoring_rule: Mapped[str] = mapped_column(String(40), nullable=False, default="mcq_v1")
    changed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("qid", "set_id", "version", name="uq_qversion_qid_setid_version"),
        ForeignKeyConstraint(
            ["qid", "set_id"],
            ["questions.qid", "questions.set_id"],
            ondelete="CASCADE",
            name="fk_qversion_to_question",
        ),
    )


# ---------------------------------------------------------------------------
# Runs + scoring
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    set_id: Mapped[str] = mapped_column(
        ForeignKey("question_sets.set_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    prompt_policy: Mapped[str] = mapped_column(
        String(60), nullable=False, default="strict_format_v1"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    set: Mapped["QuestionSet"] = relationship(back_populates="runs")
    model_runs: Mapped[list["ModelRun"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class ModelRun(Base):
    __tablename__ = "model_runs"

    model_run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["Run"] = relationship(back_populates="model_runs")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="model_run", cascade="all, delete-orphan", passive_deletes=True
    )
    aggregate: Mapped[Optional["Aggregate"]] = relationship(
        back_populates="model_run", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "model_id", name="uq_model_runs_run_model"),
        CheckConstraint("source IN ('file','api')", name="ck_model_runs_source_valid"),
    )


class Answer(Base):
    __tablename__ = "answers"

    model_run_id: Mapped[int] = mapped_column(
        ForeignKey("model_runs.model_run_id", ondelete="CASCADE"), primary_key=True
    )
    qid: Mapped[str] = mapped_column(String(20), primary_key=True)
    given_answer: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)

    model_run: Mapped["ModelRun"] = relationship(back_populates="answers")


class Aggregate(Base):
    __tablename__ = "aggregates"

    model_run_id: Mapped[int] = mapped_column(
        ForeignKey("model_runs.model_run_id", ondelete="CASCADE"), primary_key=True
    )
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    chemistry: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emotions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    math: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning3d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_knowledge: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blank_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format_violations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    model_run: Mapped["ModelRun"] = relationship(back_populates="aggregate")


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------


class Job(Base):
    """Background job persistence.

    RQ stores the live queue/state in Redis; we mirror identity and status
    here so the UI survives Redis restarts and we can query history.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
        index=True,
    )
    set_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    progress_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','error','cancelled')",
            name="ck_jobs_status_valid",
        ),
    )
