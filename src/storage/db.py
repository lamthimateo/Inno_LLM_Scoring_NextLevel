"""SQLite connection helpers + lightweight migrations.

- :func:`connect` opens a connection with ``row_factory = sqlite3.Row`` and
  ``PRAGMA foreign_keys = ON``, then runs idempotent migrations.
- :func:`init_db` applies the full schema from :mod:`src.storage.schema`.
- :func:`utc_now_iso` returns a stable ISO-8601 timestamp used everywhere
  ``created_at`` / ``updated_at`` is written.

Migrations live in :func:`_ensure_schema_migrations` and are intentionally
additive (e.g. adding the ``meta_json`` column to existing DBs).
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .schema import SCHEMA_SQL


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    """
    Lightweight migrations for already-created DBs.
    Keeps `init-db` idempotent while allowing additive schema changes.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(model_runs)").fetchall()}
    if cols and "meta_json" not in cols:
        conn.execute("ALTER TABLE model_runs ADD COLUMN meta_json TEXT;")


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _ensure_schema_migrations(conn)
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        _ensure_schema_migrations(conn)
        conn.commit()
    finally:
        conn.close()
