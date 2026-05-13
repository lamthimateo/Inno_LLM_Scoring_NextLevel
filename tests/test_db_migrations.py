"""Verify the SQLAlchemy schema can be created cleanly."""

from __future__ import annotations

from sqlalchemy import inspect

from src.storage import db as db_module
from src.storage.models import Base


EXPECTED_TABLES = {
    "users",
    "audit_log",
    "question_sets",
    "questions",
    "question_versions",
    "runs",
    "model_runs",
    "answers",
    "aggregates",
    "jobs",
    "password_reset_tokens",
}


def test_create_all_creates_every_expected_table():
    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)

    inspector = inspect(db_module.engine)
    tables = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


def test_model_runs_has_meta_json_column():
    """Sanity-check the column the v0.1 migration originally added."""

    db_module.reset_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_module.engine)

    inspector = inspect(db_module.engine)
    cols = {c["name"] for c in inspector.get_columns("model_runs")}
    assert "meta_json" in cols
