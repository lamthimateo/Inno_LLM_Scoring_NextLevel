"""Persistence helpers for a single model run (SQLAlchemy version).

Called from the run dispatcher (file-based or API-based) to:

1. Insert/upsert a row into ``model_runs`` for the raw model output, then
2. Parse + score that output against the answer key and persist
   per-question rows into ``answers`` plus the per-run row in ``aggregates``.

This module is intentionally storage-aware but provider-agnostic: it takes a
``raw_text`` string and doesn't care whether it came from a paste or an
API call.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.evaluator.parser_mcq import parse_model_output
from src.evaluator.scoring import score_answers
from src.storage.models import Aggregate, Answer, ModelRun


def _meta_json_default(o: Any) -> Any:
    """Serialize weird provider-sdk objects (Gemini ``usage_metadata``, …)."""

    # Pydantic v2 — google-genai, parts of mistral/openai responses.
    md = getattr(o, "model_dump", None)
    if callable(md):
        try:
            return md(mode="json")
        except TypeError:
            try:
                return md()
            except Exception:
                pass

    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    if isinstance(o, (set, frozenset)):
        return list(o)
    if hasattr(o, "__dict__"):
        return {
            k: v
            for k, v in vars(o).items()
            if not str(k).startswith("_")
        }
    return str(o)


def json_safe_meta(meta: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Coerce adapter ``meta`` dict into JSON-serializable data for ``meta_json``."""

    if meta is None:
        return None
    try:
        return json.loads(json.dumps(meta, default=_meta_json_default))
    except (TypeError, ValueError):
        return {"_meta_coercion_failed": True, "meta_repr": repr(meta)}


def store_model_run(
    session: Session,
    *,
    run_id: str,
    model_id: str,
    source: str,
    raw_text: str,
    meta: Optional[dict[str, Any]] = None,
) -> ModelRun:
    """Upsert one (run_id, model_id) row in ``model_runs``.

    Replaces any previous row for the same pair so re-runs are idempotent.
    """

    existing = session.execute(
        select(ModelRun).where(
            ModelRun.run_id == run_id, ModelRun.model_id == model_id
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Wipe child rows so the upsert is clean (cascade handles answers
        # and aggregate via FK with ON DELETE CASCADE).
        session.delete(existing)
        session.flush()

    mr = ModelRun(
        run_id=run_id,
        model_id=model_id,
        source=source,
        raw_text=raw_text,
        meta_json=json_safe_meta(meta),
    )
    session.add(mr)
    session.flush()
    return mr


def store_answers_and_aggregates(
    session: Session,
    *,
    model_run: ModelRun,
    answer_key: dict[str, str],
    raw_text: str,
) -> Aggregate:
    """Parse + score ``raw_text`` and persist per-question + aggregate rows."""

    parsed, format_violations = parse_model_output(raw_text)
    per_q, per_cat = score_answers(answer_key, parsed)

    correct = wrong = blank = 0
    for qid, score in per_q.items():
        given = parsed.get(qid)
        if given is None:
            blank += 1
        elif score == 1:
            correct += 1
        else:
            wrong += 1

        session.add(
            Answer(
                model_run_id=model_run.model_run_id,
                qid=qid,
                given_answer=given,
                correct_answer=answer_key.get(qid),
                score=score,
            )
        )

    total = sum(per_q.values())
    agg = Aggregate(
        model_run_id=model_run.model_run_id,
        total_score=total,
        chemistry=per_cat["chemistry"],
        emotions=per_cat["emotions"],
        math=per_cat["math"],
        reasoning3d=per_cat["reasoning3d"],
        no_knowledge=per_cat["no_knowledge"],
        contradiction=per_cat["contradiction"],
        correct_count=correct,
        wrong_count=wrong,
        blank_count=blank,
        format_violations=format_violations,
    )
    session.add(agg)
    session.flush()
    return agg
