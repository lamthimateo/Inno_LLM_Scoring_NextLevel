"""Database schema (DDL).

Single ``SCHEMA_SQL`` string applied by ``init-db``. Tables, in order:

    question_sets  -> review workflow (draft / in_review / approved / locked)
    questions      -> rows belonging to a set, identified by composite (qid, set_id)
    runs           -> one evaluation run against a set
    model_runs     -> raw model output + provider meta per (run, model)
    answers        -> per-question scoring for one model_run
    aggregates     -> per-model_run totals used by the leaderboard

Additive schema changes should also be reflected in
:func:`src.storage.db._ensure_schema_migrations` so existing DBs upgrade in
place.
"""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS question_sets (
  set_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('draft','in_review','approved','locked')),
  author TEXT,
  reviewer TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  qid TEXT NOT NULL,
  set_id TEXT NOT NULL,
  category TEXT NOT NULL,
  prompt TEXT NOT NULL,
  choices_json TEXT NOT NULL,
  correct_answer TEXT,
  scoring_rule TEXT NOT NULL,
  PRIMARY KEY (qid, set_id),
  FOREIGN KEY (set_id) REFERENCES question_sets(set_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  set_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  prompt_policy TEXT NOT NULL,
  notes TEXT,
  FOREIGN KEY (set_id) REFERENCES question_sets(set_id)
);

CREATE TABLE IF NOT EXISTS model_runs (
  model_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  source TEXT NOT NULL, -- 'file' or 'api'
  raw_text TEXT NOT NULL,
  meta_json TEXT, -- provider metadata (usage/latency/errors), JSON-encoded
  created_at TEXT NOT NULL,
  UNIQUE(run_id, model_id),
  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS answers (
  model_run_id INTEGER NOT NULL,
  qid TEXT NOT NULL,
  given_answer TEXT,
  correct_answer TEXT,
  score INTEGER NOT NULL,
  PRIMARY KEY (model_run_id, qid),
  FOREIGN KEY (model_run_id) REFERENCES model_runs(model_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS aggregates (
  model_run_id INTEGER PRIMARY KEY,
  total_score INTEGER NOT NULL,
  chemistry INTEGER NOT NULL,
  emotions INTEGER NOT NULL,
  math INTEGER NOT NULL,
  reasoning3d INTEGER NOT NULL,
  no_knowledge INTEGER NOT NULL,
  contradiction INTEGER NOT NULL,
  correct_count INTEGER NOT NULL,
  wrong_count INTEGER NOT NULL,
  blank_count INTEGER NOT NULL,
  format_violations INTEGER NOT NULL,
  FOREIGN KEY (model_run_id) REFERENCES model_runs(model_run_id) ON DELETE CASCADE
);
"""
