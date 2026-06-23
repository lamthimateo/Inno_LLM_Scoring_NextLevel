"""Results tab — finished-run gallery, leaderboard view, CSV/JSON export."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.dependencies import require_login
from src.benchmark.exporting import LEADERBOARD_COLUMNS, fetch_leaderboard_rows
from src.benchmark.queries import list_sets
from src.benchmark.runs import list_runs
from src.storage.db import get_session
from src.storage.models import (
    Answer,
    Job,
    JobStatus,
    ModelRun,
    Question,
    QuestionSet,
    Run,
    User,
)
from src.web.templating import render

router = APIRouter(prefix="/results", tags=["results"])

_TERMINAL_JOB = (
    JobStatus.DONE.value,
    JobStatus.ERROR.value,
    JobStatus.CANCELLED.value,
)


def _fmt_ts(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _choice_text(question: Question, letter: Optional[str]) -> str:
    if not letter:
        return ""
    for choice in question.choices_json or []:
        if choice.get("label") == letter:
            return str(choice.get("text") or "")
    return ""


def _answer_status(answer: Optional[Answer]) -> str:
    if answer is None:
        return "missing"
    if not answer.given_answer:
        return "blank"
    if answer.score > 0:
        return "correct"
    if answer.score < 0:
        return "wrong"
    return "blank"


def _answer_comparison_rows(
    session: Session, *, run: Run, model_runs: list[ModelRun]
) -> list[dict[str, Any]]:
    """Build question-by-question model answer comparison rows for the UI."""

    questions = session.scalars(
        select(Question).where(Question.set_id == run.set_id).order_by(Question.qid)
    ).all()
    model_run_ids = [mr.model_run_id for mr in model_runs]
    answers_by_model_run: dict[int, dict[str, Answer]] = {
        mid: {} for mid in model_run_ids
    }
    if model_run_ids:
        answers = session.scalars(
            select(Answer).where(Answer.model_run_id.in_(model_run_ids))
        ).all()
        for answer in answers:
            answers_by_model_run.setdefault(answer.model_run_id, {})[answer.qid] = answer

    rows: list[dict[str, Any]] = []
    for question in questions:
        correct = question.correct_answer
        model_cells: list[dict[str, Any]] = []
        for mr in model_runs:
            answer = answers_by_model_run.get(mr.model_run_id, {}).get(question.qid)
            given = answer.given_answer if answer is not None else None
            model_cells.append(
                {
                    "model_id": mr.model_id,
                    "given_answer": given,
                    "given_text": _choice_text(question, given),
                    "score": answer.score if answer is not None else None,
                    "status": _answer_status(answer),
                }
            )
        rows.append(
            {
                "qid": question.qid,
                "category": question.category,
                "prompt": question.prompt,
                "correct_answer": correct,
                "correct_text": _choice_text(question, correct),
                "model_cells": model_cells,
            }
        )
    return rows


@router.get("", response_class=HTMLResponse)
def results_list(
    request: Request,
    q: Optional[str] = None,
    set_id: Optional[str] = None,
    model_id: Optional[str] = None,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    raw = list_runs(session)
    cards: list[dict[str, Any]] = []
    for r in raw:
        if r.get("status") not in _TERMINAL_JOB:
            continue
        run_id = r["run_id"]
        job = session.get(Job, run_id)
        mids = list((job.payload_json or {}).get("model_ids") or []) if job else []
        rows = fetch_leaderboard_rows(session, run_id)
        best = rows[0] if rows else None
        qs = session.get(QuestionSet, r["set_id"])
        title = (qs.title or r["set_id"]) if qs else r["set_id"]
        n_q = len(qs.questions) if qs and qs.questions else 0

        hay = f"{run_id} {r['set_id']} {title} {' '.join(mids)}".lower()
        if q and q.strip() and q.strip().lower() not in hay:
            continue
        if set_id and r["set_id"] != set_id:
            continue
        if model_id and model_id not in mids:
            continue

        cards.append(
            {
                "run_id": run_id,
                "set_id": r["set_id"],
                "set_title": title,
                "status": r["status"],
                "models": mids,
                "best_model": best["model_id"] if best else None,
                "best_score": best["total"] if best else r.get("top_score"),
                "finished_at": job.finished_at if job else None,
                "finished_at_human": _fmt_ts(job.finished_at) if job else None,
                "questions_count": n_q,
            }
        )

    sets_for_filter = list_sets(session)
    all_models: set[str] = set()
    for c in cards:
        all_models.update(c["models"])

    return render(
        request,
        "results/list.html",
        current_user=user,
        active_tab="results",
        results=cards,
        filters={"q": q or "", "set_id": set_id or "", "model_id": model_id or ""},
        available_sets=sets_for_filter,
        available_models=sorted(all_models),
        total_pages=None,
    )


@router.get("/export.csv")
def export_master_csv(
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", *LEADERBOARD_COLUMNS])
    stmt = select(Run.run_id).join(Job, Job.id == Run.run_id).where(
        Job.status.in_(_TERMINAL_JOB)
    )
    for (rid,) in session.execute(stmt):
        for row in fetch_leaderboard_rows(session, rid):
            w.writerow([rid] + [row.get(c) for c in LEADERBOARD_COLUMNS])
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="all_results_leaderboard.csv"'
        },
    )


@router.get("/{run_id}/export.csv")
def export_run_csv(
    run_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    if session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    rows = fetch_leaderboard_rows(session, run_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LEADERBOARD_COLUMNS)
    for r in rows:
        writer.writerow([r.get(c) for c in LEADERBOARD_COLUMNS])
    data = buf.getvalue().encode("utf-8")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}_leaderboard.csv"'
        },
    )


@router.get("/{run_id}/export.json")
def export_run_json(
    run_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    if session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    rows = fetch_leaderboard_rows(session, run_id)
    payload = json.dumps(rows, indent=2).encode("utf-8")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)
    return StreamingResponse(
        iter([payload]),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}_leaderboard.json"'},
    )


@router.get("/{run_id}", response_class=HTMLResponse)
def results_leaderboard_page(
    request: Request,
    run_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    run = session.get(Run, run_id)
    job = session.get(Job, run_id)
    if run is None or job is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    rows = fetch_leaderboard_rows(session, run_id)
    qs = session.get(QuestionSet, run.set_id)
    run.set_title = qs.title if qs else run.set_id
    run.finished_at_human = _fmt_ts(job.finished_at)
    run.started_at_human = _fmt_ts(run.created_at)
    stmt_mr = (
        select(ModelRun)
        .where(ModelRun.run_id == run_id)
        .order_by(ModelRun.model_run_id)
    )
    model_runs = session.scalars(stmt_mr).all()
    model_outputs = [
        {"model_id": mr.model_id, "raw_text": mr.raw_text or ""}
        for mr in model_runs
    ]
    answer_comparison = _answer_comparison_rows(
        session,
        run=run,
        model_runs=model_runs,
    )
    model_errors = list((job.payload_json or {}).get("model_errors") or [])
    return render(
        request,
        "results/leaderboard.html",
        current_user=user,
        active_tab="results",
        run=run,
        rows=rows,
        model_outputs=model_outputs,
        answer_comparison=answer_comparison,
        comparison_models=[mr.model_id for mr in model_runs],
        model_errors=model_errors,
    )
