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
