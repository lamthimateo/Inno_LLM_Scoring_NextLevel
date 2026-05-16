"""Runs tab routes.

Endpoints
---------

GET  /runs                   list runs (status + top score)
GET  /runs/new               new-run form
POST /runs/new               create + start background run, redirect
GET  /runs/{run_id}          detail (auto-polls progress + leaderboard)
GET  /runs/{run_id}/status   HTMX fragment for progress polling
POST /runs/{run_id}/cancel   request cancellation of an in-flight run
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.adapters.registry import (
    DEFAULT_MODELS,
    MODEL_CATALOG,
    catalog_by_id,
    catalog_entry_env_ok,
    catalog_grouped,
    default_catalog_ids,
    group_is_available,
)
from src.auth.dependencies import require_login
from src.benchmark.exporting import fetch_leaderboard_rows
from src.benchmark.queries import list_sets
from src.benchmark.runs import (
    RunError,
    create_run,
    list_runs,
    request_cancellation,
    run_in_background,
    run_model_slots,
)
from src.storage.db import get_session
from src.storage.models import (
    AuditLog,
    Job,
    JobStatus,
    ModelRun,
    QuestionSet,
    Run,
    SetStatus,
    User,
    UserRole,
)
from src.web.templating import render


router = APIRouter(prefix="/runs", tags=["runs"])


def _fmt_ts_human(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


@router.get("", response_class=HTMLResponse)
def list_view(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    raw = list_runs(session)
    rid_list = [r["run_id"] for r in raw]
    jobs_map: dict[str, Job] = {}
    if rid_list:
        stmt_jobs = select(Job).where(Job.id.in_(rid_list))
        for j in session.scalars(stmt_jobs).all():
            jobs_map[j.id] = j

    # Adapt the dict shape coming out of list_runs() to the keys the
    # design-system runs/list.html template expects.
    runs = []
    for r in raw:
        job = jobs_map.get(r["run_id"])
        models = list((job.payload_json or {}).get("model_ids") or []) if job else []
        runs.append(
            {
                **r,
                "models": models,
                "set_title": r.get("set_id"),
                "started_by": r.get("started_by_username"),
                "started_at": r.get("created_at"),
                "started_at_human": _fmt_ts_human(r.get("created_at")),
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
        active_tab="runs",
        runs=runs,
        locked_sets=locked_sets,
        default_models=DEFAULT_MODELS,
        **_catalog_context(),
        filters={"status": status or "", "q": q or ""},
    )


def _catalog_context() -> dict:
    """Template kwargs that drive the model picker on runs/new.html."""

    defaults = default_catalog_ids()
    return {
        "model_catalog": MODEL_CATALOG,
        "model_catalog_grouped": catalog_grouped(),
        "model_catalog_defaults": defaults,
        "model_catalog_group_available": {
            group: group_is_available(group)
            for group, _entries in catalog_grouped()
        },
    }


def _validate_selected_models(
    raw: List[str],
) -> tuple[List[str], Optional[str]]:
    """Resolve the form-submitted model ids against the curated catalog.

    Returns ``(model_ids, error)``. ``error`` is ``None`` on success.

    Rules
    -----
    - Empty selection → silently fall back to :func:`default_catalog_ids`.
    - Unknown id → flash error, no fallback.
    - Known id whose required env var is missing → flash error.
    - Duplicates → de-duplicated while preserving submission order.
    """

    cleaned = [m.strip() for m in raw if m and m.strip()]
    seen: dict[str, None] = {}
    for m in cleaned:
        seen.setdefault(m, None)
    cleaned = list(seen.keys())

    if not cleaned:
        return default_catalog_ids(), None

    by_id = catalog_by_id()
    unknown = [m for m in cleaned if m not in by_id]
    if unknown:
        return [], (
            "Unknown model id"
            f"{'s' if len(unknown) > 1 else ''}: "
            f"{', '.join(repr(m) for m in unknown)}. "
            "Pick from the curated list."
        )

    missing_env: list[tuple[str, str]] = []
    for m in cleaned:
        entry = by_id[m]
        if not catalog_entry_env_ok(entry):
            env_label = (
                "OPENROUTER_API_KEY or OPENROUTER_API"
                if entry.requires_env == "OPENROUTER_API_KEY"
                else entry.requires_env
            )
            missing_env.append((entry.label, env_label))
    if missing_env:
        labels = ", ".join(f"{lbl} (needs {env})" for lbl, env in missing_env)
        return [], (
            f"These models require a provider key that isn't set: {labels}. "
            "Add it to .env and restart the app."
        )

    return cleaned, None


@router.get("/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    locked_sets = [
        s for s in list_sets(session, status=SetStatus.LOCKED.value)
    ]
    defaults = default_catalog_ids()
    return render(
        request,
        "runs/new.html",
        current_user=user,
        active_tab="runs",
        locked_sets=locked_sets,
        default_models=DEFAULT_MODELS,
        **_catalog_context(),
        error=None,
        form={"set_id": "", "selected_models": defaults, "notes": ""},
    )


@router.post("/new")
def new_submit(
    request: Request,
    set_id: str = Form(...),
    models: Optional[List[str]] = Form(default=None),
    notes: str = Form(""),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    model_ids, error = _validate_selected_models(models or [])
    if error is not None:
        session.rollback()
        locked_sets = list_sets(session, status=SetStatus.LOCKED.value)
        return render(
            request,
            "runs/new.html",
            current_user=user,
            active_tab="runs",
            locked_sets=locked_sets,
            default_models=DEFAULT_MODELS,
            **_catalog_context(),
            error=error,
            form={"set_id": set_id, "selected_models": models, "notes": notes},
            status_code=400,
        )

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
            active_tab="runs",
            locked_sets=locked_sets,
            default_models=DEFAULT_MODELS,
            **_catalog_context(),
            error=str(exc),
            form={"set_id": set_id, "selected_models": models, "notes": notes},
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
    model_runs = run_model_slots(session, run_id=run_id, job=job)
    stmt_mr = (
        select(ModelRun)
        .where(ModelRun.run_id == run_id)
        .order_by(ModelRun.model_run_id)
    )
    model_outputs = [
        {"model_id": mr.model_id, "raw_text": mr.raw_text or ""}
        for mr in session.scalars(stmt_mr).all()
    ]

    qs = session.get(QuestionSet, run.set_id)
    run.status = job.status
    run.set_title = (qs.title or run.set_id) if qs else run.set_id
    starter = session.get(User, run.started_by_id) if run.started_by_id else None
    run.started_by = starter.username if starter else "—"
    run.started_at = run.created_at
    run.started_at_human = _fmt_ts_human(run.created_at)
    run.finished_at = job.finished_at
    run.finished_at_human = _fmt_ts_human(job.finished_at)
    run.partial_aggregates = []

    return render(
        request,
        "runs/detail.html",
        current_user=user,
        active_tab="runs",
        run=run,
        job=job,
        rows=rows,
        model_runs=model_runs,
        model_outputs=model_outputs,
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
    model_runs = run_model_slots(session, run_id=run_id, job=job)
    return render(
        request,
        "runs/_run_live_fragment.html",
        current_user=user,
        active_tab="runs",
        run=run,
        job=job,
        rows=rows,
        model_runs=model_runs,
    )


_ACTIVE_JOB_STATES = {JobStatus.QUEUED.value, JobStatus.RUNNING.value}


@router.post("/{run_id}/cancel")
def cancel(
    request: Request,
    run_id: str,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    """Request cancellation of an in-flight run.

    - 404 if the run/job is unknown.
    - 403 if the caller is neither the user who started the run nor an admin.
    - 303 redirect back to the run detail page on success (204 + ``HX-Redirect``
      header when called via HTMX so the polling fragment refreshes cleanly).
    - Idempotent for finished runs: a no-op redirect, never a 5xx.
    """

    run = session.get(Run, run_id)
    job = session.get(Job, run_id)
    if run is None or job is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    if run.started_by_id != user.id and user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Only the user who started this run (or an admin) can cancel it.",
        )

    if job.status in _ACTIVE_JOB_STATES:
        # Flip the in-process flag so the orchestrator thread exits cleanly
        # between models. The thread will *also* set status=cancelled when it
        # observes the flag, but we mirror it here so the next /status poll
        # reflects the new state immediately without waiting for the current
        # model call to return.
        request_cancellation(run_id)
        job.status = JobStatus.CANCELLED.value
        job.finished_at = datetime.now(timezone.utc)
        job.message = (job.message or "") + (
            " · cancelled by user" if job.message else "Cancelled by user."
        )
        session.add(
            AuditLog(
                actor_id=user.id,
                action="run.cancelled",
                target_type="run",
                target_id=run_id,
            )
        )
        session.commit()

    if request.headers.get("HX-Request"):
        return Response(
            status_code=204,
            headers={"HX-Redirect": f"/runs/{run_id}"},
        )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
