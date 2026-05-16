"""Runs orchestration.

A :class:`Run` is one evaluation of a locked question set against one or
more models. This module wires the pieces together:

1. :func:`create_run`             insert ``runs`` row + ``jobs`` row.
2. :func:`execute_run`             load locked set, build prompt, call each
                                   adapter, persist ``model_runs``,
                                   ``answers`` and ``aggregates``.
3. :func:`run_in_background`       spawn a thread that opens its own DB
                                   session and runs ``execute_run`` —
                                   suitable for FastAPI BackgroundTasks.

Errors from individual model calls are captured on the per-model
``Job`` / ``ModelRun`` row; one bad provider does not abort the rest.

Cancellation
------------

The HTTP route ``POST /runs/{run_id}/cancel`` flips two switches:

- It writes ``Job.status = 'cancelled'`` so the UI sees the new state
  immediately on its next poll.
- It calls :func:`request_cancellation`, which sets a process-local
  :class:`threading.Event`. The orchestrator loop in :func:`execute_run`
  checks this event between models and exits cleanly, leaving the
  results of already-completed models in place.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.adapters.registry import get_adapter
from src.benchmark.importing import load_answer_key
from src.benchmark.pipeline import store_answers_and_aggregates, store_model_run
from src.benchmark.prompting import build_prompt_text
from src.storage import db as _db
from src.storage.models import (
    AuditLog,
    Job,
    JobStatus,
    ModelRun,
    Run,
    QuestionSet,
    SetStatus,
)


log = logging.getLogger(__name__)


class RunError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Cancellation flags
# ---------------------------------------------------------------------------
#
# Cancellation lives in-process: the orchestrator thread for ``run_id`` checks
# this map between model calls and exits early when the corresponding event
# is set. This is sufficient for the single-app-process deployment we ship
# today; a multi-worker setup would need to back this with Redis instead.

_cancellation_events: dict[str, threading.Event] = {}
_cancellation_lock = threading.Lock()


def request_cancellation(run_id: str) -> None:
    """Ask the orchestrator thread for ``run_id`` to stop before the next model.

    Idempotent — repeated calls leave the event set.
    """

    with _cancellation_lock:
        event = _cancellation_events.get(run_id)
        if event is None:
            event = threading.Event()
            _cancellation_events[run_id] = event
        event.set()


def is_cancellation_requested(run_id: str) -> bool:
    """Return ``True`` iff :func:`request_cancellation` was called for ``run_id``."""

    with _cancellation_lock:
        event = _cancellation_events.get(run_id)
    return bool(event and event.is_set())


def clear_cancellation(run_id: str) -> None:
    """Drop the cancellation entry for ``run_id`` (called when the run finishes)."""

    with _cancellation_lock:
        _cancellation_events.pop(run_id, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_run(
    session: Session,
    *,
    set_id: str,
    model_ids: list[str],
    started_by_id: Optional[int] = None,
    notes: Optional[str] = None,
    run_id: Optional[str] = None,
) -> tuple[Run, Job]:
    """Insert the ``runs`` row + companion ``jobs`` row.

    The set must be ``locked`` — that's the reproducibility guarantee.
    """

    qs = session.get(QuestionSet, set_id)
    if qs is None:
        raise RunError(f"Unknown set_id: {set_id!r}")
    if qs.status != SetStatus.LOCKED.value:
        raise RunError(
            f"Set {set_id!r} is {qs.status!r}. Only locked sets can be evaluated."
        )

    cleaned = [m.strip() for m in model_ids if m and m.strip()]
    if not cleaned:
        raise RunError("Pick at least one model.")

    rid = run_id or _new_run_id()

    run = Run(
        run_id=rid,
        set_id=set_id,
        notes=notes,
        started_by_id=started_by_id,
    )
    job = Job(
        id=rid,
        kind="evaluation_run",
        status=JobStatus.QUEUED.value,
        set_id=set_id,
        run_id=rid,
        created_by_id=started_by_id,
        payload_json={"model_ids": cleaned},
        progress_total=len(cleaned),
        progress_done=0,
    )
    session.add_all([run, job])
    session.add(
        AuditLog(
            actor_id=started_by_id,
            action="create_run",
            target_type="run",
            target_id=rid,
            payload_json={"set_id": set_id, "model_ids": cleaned},
        )
    )
    session.flush()
    return run, job


def execute_run(session: Session, run_id: str) -> Job:
    """Run every model listed in the companion Job, in series, writing
    ``model_runs`` + ``answers`` + ``aggregates`` per success and updating
    the Job's progress and status.

    Safe to retry: existing model_runs for the same (run_id, model_id) are
    replaced (see :func:`store_model_run`).
    """

    job = session.get(Job, run_id)
    run = session.get(Run, run_id)
    if job is None or run is None:
        raise RunError(f"Unknown run: {run_id!r}")
    payload = job.payload_json or {}
    model_ids: list[str] = list(payload.get("model_ids") or [])
    if not model_ids:
        raise RunError("Job is missing model_ids in payload.")

    prompt = build_prompt_text(session, run.set_id)
    answer_key = load_answer_key(session, run.set_id)

    job.status = JobStatus.RUNNING.value
    job.started_at = datetime.now(timezone.utc)
    job.progress_done = 0
    job.progress_total = len(model_ids)
    session.flush()
    session.commit()

    errors: list[dict[str, Any]] = []
    completed = 0
    cancelled = False
    for idx, model_id in enumerate(model_ids, start=1):
        if is_cancellation_requested(run_id):
            cancelled = True
            log.info(
                "run.cancellation_observed run_id=%s before_model=%s", run_id, model_id
            )
            break
        try:
            adapter = get_adapter(model_id)
            if not adapter.is_configured():
                raise RunError(
                    f"Adapter for {model_id!r} is not configured "
                    f"(missing API key)."
                )
            result = adapter.run(prompt)
            mr = store_model_run(
                session,
                run_id=run_id,
                model_id=adapter.id(),
                source="api",
                raw_text=result.raw_text or "",
                meta=result.meta,
            )
            store_answers_and_aggregates(
                session,
                model_run=mr,
                answer_key=answer_key,
                raw_text=result.raw_text or "",
            )
            job.progress_done = idx
            completed = idx
            session.flush()
            session.commit()
            log.info("run.model_done run_id=%s model=%s", run_id, model_id)
        except Exception as exc:
            session.rollback()
            errors.append({"model_id": model_id, "error": str(exc)})
            log.exception("run.model_failed run_id=%s model=%s", run_id, model_id)
            # Reload job after rollback
            job = session.get(Job, run_id)
            job.progress_done = idx
            completed = idx
            session.flush()
            session.commit()

    job = session.get(Job, run_id)
    job.finished_at = datetime.now(timezone.utc)
    if cancelled:
        # The cancel route already wrote status=cancelled; if it didn't run
        # first (race condition between observation and the HTTP write), do
        # it ourselves. Either way, the cancellation reason wins over the
        # success/error summary below.
        job.status = JobStatus.CANCELLED.value
        remaining = len(model_ids) - completed
        job.message = (
            f"Cancelled after {completed}/{len(model_ids)} models "
            f"({remaining} not started)."
        )
        if errors:
            job.error = "; ".join(f"{e['model_id']}: {e['error']}" for e in errors)
    elif errors and len(errors) == len(model_ids):
        job.status = JobStatus.ERROR.value
        job.error = "; ".join(f"{e['model_id']}: {e['error']}" for e in errors)
    elif errors:
        # Partial success: mark done but record errors in the payload.
        job.status = JobStatus.DONE.value
        job.message = (
            f"{len(model_ids) - len(errors)}/{len(model_ids)} models succeeded."
        )
        job.error = "; ".join(f"{e['model_id']}: {e['error']}" for e in errors)
    else:
        job.status = JobStatus.DONE.value
        job.message = f"All {len(model_ids)} models succeeded."
    session.flush()
    session.commit()
    clear_cancellation(run_id)
    return job


def run_in_background(run_id: str) -> threading.Thread:
    """Spawn a daemon thread that opens its own DB session and runs.

    Use this from a FastAPI endpoint to avoid blocking the response.
    """

    def _target():
        # Resolve SessionLocal lazily so tests that swap the engine
        # (via :func:`src.storage.db.reset_engine`) get the right one.
        session = _db.SessionLocal()
        try:
            execute_run(session, run_id)
        except Exception:
            log.exception("background run failed run_id=%s", run_id)
            session.rollback()
            job = session.get(Job, run_id)
            if job is not None:
                job.status = JobStatus.ERROR.value
                job.finished_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()

    t = threading.Thread(target=_target, name=f"run-{run_id}", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"run_{now}_{uuid.uuid4().hex[:6]}"


def list_runs(session: Session) -> list[dict[str, Any]]:
    """One row per run with status + counts for the list view."""

    from sqlalchemy import func
    from src.storage.models import Aggregate
    from src.storage.models import User as U

    stmt = (
        select(
            Run.run_id,
            Run.set_id,
            Run.created_at,
            Job.status,
            Job.progress_done,
            Job.progress_total,
            Job.message,
            Job.error,
            func.count(ModelRun.model_run_id).label("model_runs"),
            func.coalesce(func.max(Aggregate.total_score), 0).label("top_score"),
            U.username.label("started_by_username"),
        )
        .select_from(Run)
        .outerjoin(Job, Job.id == Run.run_id)
        .outerjoin(ModelRun, ModelRun.run_id == Run.run_id)
        .outerjoin(Aggregate, Aggregate.model_run_id == ModelRun.model_run_id)
        .outerjoin(U, U.id == Run.started_by_id)
        .group_by(
            Run.run_id, Run.set_id, Run.created_at, Job.status,
            Job.progress_done, Job.progress_total, Job.message, Job.error,
            U.username,
        )
        .order_by(Run.created_at.desc())
    )
    return [dict(r._mapping) for r in session.execute(stmt).all()]


def run_model_slots(session: Session, *, run_id: str, job: Job) -> list[dict[str, Any]]:
    """Align ``job.payload_json.model_ids`` with :class:`ModelRun` rows for the UI."""

    payload = job.payload_json or {}
    model_ids: list[str] = list(payload.get("model_ids") or [])
    if not model_ids:
        return []

    stmt = select(ModelRun).where(ModelRun.run_id == run_id).order_by(ModelRun.model_run_id)
    by_mid: dict[str, ModelRun] = {mr.model_id: mr for mr in session.scalars(stmt).all()}

    st_job = job.status
    pd = job.progress_done or 0
    terminal = st_job in (
        JobStatus.DONE.value,
        JobStatus.ERROR.value,
        JobStatus.CANCELLED.value,
    )

    out: list[dict[str, Any]] = []
    for i, mid in enumerate(model_ids):
        short = mid.split(":", 1)[-1] if ":" in mid else mid
        if mid in by_mid:
            out.append(
                {
                    "model_id": mid,
                    "label": short,
                    "status": "done",
                    "percent": 100,
                    "error_message": None,
                }
            )
            continue

        if st_job == JobStatus.QUEUED.value:
            slot_status = "queued"
            pct = 0
        elif st_job == JobStatus.RUNNING.value:
            if i < pd:
                slot_status = "error"
                pct = 0
            elif i == pd:
                slot_status = "running"
                pct = 50
            else:
                slot_status = "queued"
                pct = 0
        elif st_job == JobStatus.CANCELLED.value:
            if i >= pd:
                slot_status = "cancelled"
            else:
                slot_status = "error"
            pct = 0
        else:
            slot_status = "error"
            pct = 0

        out.append(
            {
                "model_id": mid,
                "label": short,
                "status": slot_status,
                "percent": pct,
                "error_message": None,
            }
        )

    if terminal and job.error:
        err_blob = job.error
        for row in out:
            if row["status"] not in ("error", "cancelled"):
                continue
            mid = row["model_id"]
            prefix = f"{mid}:"
            if prefix in err_blob:
                idx = err_blob.index(prefix)
                tail = err_blob[idx + len(prefix) :].strip()
                row["error_message"] = tail.split(";", 1)[0].strip()
            elif mid in err_blob and row["status"] == "error":
                row["error_message"] = err_blob[:800]

    return out
