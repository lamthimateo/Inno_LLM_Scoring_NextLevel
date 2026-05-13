"""Export a finished run to CSV + static leaderboard assets.

Joins ``model_runs`` with ``aggregates`` for the given ``run_id`` and writes:

- ``<out_dir>/benchmark_results.csv`` — one row per model
- ``<out_dir>/leaderboard/leaderboard.json`` — same data as JSON
- ``<out_dir>/leaderboard/index.html`` — self-contained dashboard (no JS deps)

The leaderboard HTML lives in :mod:`src.web.leaderboard`.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Aggregate, ModelRun
from src.web.leaderboard import write_leaderboard_assets


LEADERBOARD_COLUMNS = (
    "model_id",
    "total",
    "chemistry",
    "emotions",
    "math",
    "reasoning3d",
    "no_knowledge",
    "contradiction",
    "correct",
    "wrong",
    "blank",
    "format_violations",
)


def fetch_leaderboard_rows(session: Session, run_id: str) -> list[dict[str, Any]]:
    """Return one row per model in ``run_id``, sorted by total score desc.

    Each row has the keys defined in :data:`LEADERBOARD_COLUMNS`.
    """

    stmt = (
        select(
            ModelRun.model_id,
            Aggregate.total_score.label("total"),
            Aggregate.chemistry,
            Aggregate.emotions,
            Aggregate.math,
            Aggregate.reasoning3d,
            Aggregate.no_knowledge,
            Aggregate.contradiction,
            Aggregate.correct_count.label("correct"),
            Aggregate.wrong_count.label("wrong"),
            Aggregate.blank_count.label("blank"),
            Aggregate.format_violations,
        )
        .join(Aggregate, Aggregate.model_run_id == ModelRun.model_run_id)
        .where(ModelRun.run_id == run_id)
        .order_by(Aggregate.total_score.desc())
    )
    return [dict(r._mapping) for r in session.execute(stmt).all()]


def export_results(session: Session, *, run_id: str, out_dir: str | Path) -> Path:
    """Write CSV + leaderboard assets. Returns the output dir."""

    rows = fetch_leaderboard_rows(session, run_id)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "benchmark_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(LEADERBOARD_COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in LEADERBOARD_COLUMNS])

    write_leaderboard_assets(rows, str(out / "leaderboard"))
    return out
