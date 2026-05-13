"""Runs tab routes.

Endpoints
---------

GET  /runs                   list runs (status + top score)
GET  /runs/new               new-run form
POST /runs/new               create + start background run, redirect
GET  /runs/{run_id}          detail (auto-polls progress + leaderboard)
GET  /runs/{run_id}/status   HTMX fragment for progress polling
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.adapters.registry import DEFAULT_MODELS
from src.auth.dependencies import require_login
from src.benchmark.exporting import fetch_leaderboard_rows
from src.benchmark.queries import list_sets
from src.benchmark.runs import RunError, create_run, list_runs, run_in_background
from src.storage.db import get_session
from src.storage.models import Job, Run, SetStatus, User
from src.web.templating import render


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_class=HTMLResponse)
def list_view(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    raw = list_runs(session)
    # Adapt the dict shape coming out of list_runs() to the keys the
    # design-system runs/list.html template expects.
    runs = []
    for r in raw:
        models = []  # we don't yet store the per-run model-ids list outside
                    # the Job payload; cheap stub for the chip row.
        runs.append(
            {
                **r,
                "models": models,
                "set_title": r.get("set_id"),
                "started_by": r.get("started_by_username"),
                "started_at": r.get("created_at"),
                "best_score": r.get("top_score"),
            }
        )
    # The runs/list.html template embeds the "New run" modal (runs/new.html),
    # which iterates over ``locked_sets`` to populate its set picker. We must
    # fetch them here for any authenticated user — locked sets are runnable
    # regardless of who authored or reviewed them.
    locked_sets = list_sets(session, status=SetStatus.LOCKED.value)
    return render(
        request,
        "runs/list.html",
        current_user=user,
        active_tab="results",
        runs=runs,
        locked_sets=locked_sets,
        default_models=DEFAULT_MODELS,
        filters={"status": status or "", "q": q or ""},
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    locked_sets = [
        s for s in list_sets(session, status=SetStatus.LOCKED.value)
    ]
    return render(
        request,
        "runs/new.html",
        current_user=user,
        active_tab="results",
        locked_sets=locked_sets,
        default_models=DEFAULT_MODELS,
        error=None,
        form={"set_id": "", "model_ids_csv": "\n".join(DEFAULT_MODELS), "notes": ""},
    )


@router.post("/new")
def new_submit(
    request: Request,
    set_id: str = Form(...),
    model_ids_csv: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    model_ids = [
        line.strip()
        for line in model_ids_csv.replace(",", "\n").splitlines()
        if line.strip()
    ]

    try:
        run, _job = create_run(
            session,
            set_id=set_id,
            model_ids=model_ids,
            started_by_id=user.id,
            notes=notes.strip() or None,
        )
    except RunError as exc:
        session.rollback()
        locked_sets = list_sets(session, status=SetStatus.LOCKED.value)
        return render(
            request,
            "runs/new.html",
            current_user=user,
            active_tab="results",
            locked_sets=locked_sets,
            default_models=DEFAULT_MODELS,
            error=str(exc),
            form={"set_id": set_id, "model_ids_csv": model_ids_csv, "notes": notes},
            status_code=400,
        )

    session.commit()
    run_in_background(run.run_id)
    return RedirectResponse(url=f"/runs/{run.run_id}", status_code=303)


@router.get("/{run_id}", response_class=HTMLResponse)
def detail(
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
    # Decorate ``run`` with extras the polished detail template asks for.
    run.status = job.status
    run.set_title = run.set_id
    run.started_by = None
    run.started_at = run.created_at
    run.partial_aggregates = []
    run.model_runs = []
    return render(
        request,
        "runs/detail.html",
        current_user=user,
        active_tab="results",
        run=run,
        job=job,
        rows=rows,
    )


@router.get("/{run_id}/status", response_class=HTMLResponse)
def status_fragment(
    request: Request,
    run_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    """HTMX polling endpoint — renders only the status + leaderboard card."""

    run = session.get(Run, run_id)
    job = session.get(Job, run_id)
    if run is None or job is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    rows = fetch_leaderboard_rows(session, run_id)
    return render(
        request,
        "runs/_status_fragment.html",
        current_user=user,
        active_tab="results",
        run=run,
        job=job,
        rows=rows,
    )
