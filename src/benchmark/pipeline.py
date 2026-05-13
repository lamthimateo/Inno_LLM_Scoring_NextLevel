"""Persistence helpers for a single model run.

This module is the bridge between "raw model output" and "rows in SQLite".
It is called from both ``run-file`` and ``run-openai`` so that the storage
shape stays identical regardless of how the output was produced.

Functions:

- :func:`load_answer_key` reads ``{qid: correct_answer}`` for a set.
- :func:`store_model_run` inserts/updates the raw output row and returns its
  surrogate ``model_run_id``.
- :func:`store_answers_and_aggregates` parses the raw output, scores it
  against the answer key, and persists both per-question rows and the
  per-run aggregate row used by the leaderboard.
"""

import json
from typing import Dict, Optional

from src.evaluator.parser_mcq import parse_model_output
from src.evaluator.scoring import score_answers


def load_answer_key(conn, set_id: str) -> Dict[str, str]:
    return {
        r["qid"]: r["correct_answer"]
        for r in conn.execute("SELECT qid, correct_answer FROM questions WHERE set_id=?", (set_id,))
    }


def store_model_run(
    conn,
    *,
    run_id: str,
    model_id: str,
    source: str,
    raw_text: str,
    meta: Optional[dict],
    created_at: str,
) -> int:
    meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
    conn.execute(
        "INSERT OR REPLACE INTO model_runs(run_id,model_id,source,raw_text,meta_json,created_at) VALUES(?,?,?,?,?,?)",
        (run_id, model_id, source, raw_text, meta_json, created_at),
    )
    return conn.execute(
        "SELECT model_run_id FROM model_runs WHERE run_id=? AND model_id=?",
        (run_id, model_id),
    ).fetchone()["model_run_id"]


def store_answers_and_aggregates(conn, *, model_run_id: int, answer_key: dict, raw_text: str) -> None:
    parsed, format_violations = parse_model_output(raw_text)
    per_q, per_cat = score_answers(answer_key, parsed)

    correct = wrong = blank = 0
    for qid, s in per_q.items():
        given = parsed.get(qid)
        if given is None:
            blank += 1
        elif s == 1:
            correct += 1
        else:
            wrong += 1

        conn.execute(
            "INSERT OR REPLACE INTO answers(model_run_id,qid,given_answer,correct_answer,score) VALUES(?,?,?,?,?)",
            (model_run_id, qid, given, answer_key.get(qid), s),
        )

    total = sum(per_q.values())
    conn.execute(
        """INSERT OR REPLACE INTO aggregates(
               model_run_id,total_score,chemistry,emotions,math,reasoning3d,no_knowledge,contradiction,
               correct_count,wrong_count,blank_count,format_violations
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            model_run_id,
            total,
            per_cat["chemistry"],
            per_cat["emotions"],
            per_cat["math"],
            per_cat["reasoning3d"],
            per_cat["no_knowledge"],
            per_cat["contradiction"],
            correct,
            wrong,
            blank,
            format_violations,
        ),
    )

