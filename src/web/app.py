"""FastAPI dashboard.

Lets you start ``run-openai`` jobs from a browser instead of the CLI:

    uvicorn src.web.app:app --reload --port 8000

Endpoints:

    GET  /                       -> form + list of question sets + recent jobs
    POST /run-openai             -> queue a background OpenAI run
    GET  /jobs/{job_id}          -> job status + link to the rendered leaderboard
    GET  /runs/{run_id}/leaderboard -> serve the static index.html for a run

Jobs are stored in-memory only (``_jobs`` dict). The DB path defaults to
``db/benchmark.db`` at the repo root; pass ``?db=...`` to override.
Reads ``OPENAI_API_KEY`` from the server process environment.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from src.benchmark.constants import default_db_path
from src.benchmark.exporting import export_results as export_results_impl
from src.benchmark.cli import run_openai as run_openai_impl
from src.storage.db import connect, init_db


@dataclass
class Job:
    job_id: str
    status: str  # queued|running|done|error
    message: str
    run_id: str
    set_id: str
    created_at_s: float


app = FastAPI(title="Inno LLM Scoring Web")

ROOT = Path(__file__).resolve().parents[2]
DB_DEFAULT = default_db_path(str(ROOT))
RESULTS_BASE = ROOT / "results" / "web"

_jobs: Dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;margin:22px;max-width:980px}}
    h1{{margin:0 0 8px 0}}
    .muted{{color:#5b616e}}
    .card{{border:1px solid #e5e7eb;border-radius:14px;padding:14px;margin:14px 0}}
    label{{display:block;margin:10px 0 6px 0;font-weight:600}}
    input,select{{padding:10px 12px;border:1px solid #d1d5db;border-radius:12px;width:min(620px,100%)}}
    .row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
    button{{padding:10px 12px;border:1px solid #d1d5db;border-radius:12px;background:#fff;cursor:pointer}}
    code{{background:#f3f4f6;padding:2px 6px;border-radius:8px}}
    a{{color:#2563eb;text-decoration:none}}
    a:hover{{text-decoration:underline}}
    table{{width:100%;border-collapse:collapse}}
    th,td{{text-align:left;padding:8px;border-bottom:1px solid #eee;font-size:13px}}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _list_sets(db_path: str):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT set_id,status,author,reviewer,created_at,updated_at FROM question_sets ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _ensure_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if not Path(db_path).exists():
        init_db(db_path)


def _new_job(job: Job) -> None:
    with _jobs_lock:
        _jobs[job.job_id] = job


def _update_job(job_id: str, *, status: str, message: str) -> None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None:
            return
        j.status = status
        j.message = message


def _run_openai_job(
    *,
    job_id: str,
    db_path: str,
    set_id: str,
    run_id: str,
    models_csv: str,
    temperature: float,
    max_output_tokens: int,
    timeout_s: float,
    max_retries: int,
    prompt_policy: str,
    notes: str,
) -> None:
    _update_job(job_id, status="running", message="Running OpenAI requests…")
    try:
        conn = connect(db_path)
        try:
            run_openai_impl(
                conn,
                set_id=set_id,
                run_id=run_id,
                models_csv=models_csv,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
                max_retries=max_retries,
                prompt_policy=prompt_policy,
                notes=notes,
            )
            conn.commit()
        finally:
            conn.close()

        _update_job(job_id, status="running", message="Exporting leaderboard…")
        out_dir = RESULTS_BASE / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        conn = connect(db_path)
        try:
            export_results_impl(conn, run_id=run_id, out_dir=str(out_dir))
        finally:
            conn.close()

        _update_job(job_id, status="done", message="Done")
    except Exception as e:
        _update_job(job_id, status="error", message=f"{e.__class__.__name__}: {e}")


@app.get("/", response_class=HTMLResponse)
def home(db: str = DB_DEFAULT):
    _ensure_db(db)
    sets = _list_sets(db)
    sets_html = (
        "<tr><th>set_id</th><th>status</th><th>author</th><th>reviewer</th><th>updated</th></tr>"
        + "\n".join(
            f"<tr><td><code>{s['set_id']}</code></td><td>{s['status']}</td><td>{s.get('author') or ''}</td><td>{s.get('reviewer') or ''}</td><td>{s.get('updated_at') or ''}</td></tr>"
            for s in sets
        )
        if sets
        else "<div class='muted'>No sets in DB yet. Import questions first using the CLI.</div>"
    )

    body = f"""
<h1>Inno LLM Scoring (Web)</h1>
<div class="muted">Run OpenAI from a browser. Server uses <code>OPENAI_API_KEY</code> from environment.</div>

<div class="card">
  <h2 style="margin:0 0 10px 0">Run OpenAI</h2>
  <form method="post" action="/run-openai">
    <label>DB path</label>
    <input name="db" value="{db}" />

    <label>set_id</label>
    <input name="set_id" placeholder="benchmark_v1" />

    <label>run_id</label>
    <input name="run_id" placeholder="run_openai_001" />

    <label>models (comma-separated)</label>
    <input name="models" placeholder="gpt-4.1,gpt-4.1-mini" />

    <div class="row">
      <div>
        <label>temperature</label>
        <input name="temperature" value="0.0" />
      </div>
      <div>
        <label>max_output_tokens</label>
        <input name="max_output_tokens" value="2048" />
      </div>
      <div>
        <label>timeout_s</label>
        <input name="timeout_s" value="120" />
      </div>
      <div>
        <label>max_retries</label>
        <input name="max_retries" value="3" />
      </div>
    </div>

    <label>notes (optional)</label>
    <input name="notes" value="" />

    <div style="margin-top:12px">
      <button type="submit">Start run</button>
    </div>
  </form>
</div>

<div class="card">
  <h2 style="margin:0 0 10px 0">Sets in DB</h2>
  <table>{sets_html}</table>
  <div class="muted" style="margin-top:8px">Tip: set must be <code>approved</code> or <code>locked</code> to run.</div>
</div>

<div class="card">
  <h2 style="margin:0 0 10px 0">Jobs</h2>
  <div class="muted">Open a job link to see status and the generated leaderboard.</div>
  <ul>
    {''.join(f'<li><a href="/jobs/{jid}">{jid}</a> — {j.status}</li>' for jid, j in list(_jobs.items())[::-1][:12])}
  </ul>
</div>
"""
    return _html_page("Inno LLM Scoring Web", body)


@app.post("/run-openai")
def run_openai(
    db: str = Form(DB_DEFAULT),
    set_id: str = Form(...),
    run_id: str = Form(...),
    models: str = Form(...),
    temperature: float = Form(0.0),
    max_output_tokens: int = Form(2048),
    timeout_s: float = Form(120.0),
    max_retries: int = Form(3),
    notes: str = Form(""),
):
    _ensure_db(db)
    if not os.getenv("OPENAI_API_KEY"):
        return HTMLResponse(
            _html_page(
                "Missing OPENAI_API_KEY",
                "<h1>Missing OPENAI_API_KEY</h1><p>Export <code>OPENAI_API_KEY</code> in the server environment, then reload.</p>",
            ),
            status_code=400,
        )

    job_id = f"job_{int(time.time())}_{run_id}"
    _new_job(
        Job(
            job_id=job_id,
            status="queued",
            message="Queued",
            run_id=run_id,
            set_id=set_id,
            created_at_s=time.time(),
        )
    )

    t = threading.Thread(
        target=_run_openai_job,
        daemon=True,
        kwargs=dict(
            job_id=job_id,
            db_path=db,
            set_id=set_id,
            run_id=run_id,
            models_csv=models,
            temperature=float(temperature),
            max_output_tokens=int(max_output_tokens),
            timeout_s=float(timeout_s),
            max_retries=int(max_retries),
            prompt_policy="strict_format_v1",
            notes=notes,
        ),
    )
    t.start()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_status(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if j is None:
        return HTMLResponse(_html_page("Not found", "<h1>Job not found</h1>"), status_code=404)

    lb_path = RESULTS_BASE / j.run_id / "leaderboard" / "index.html"
    lb_link = f"/runs/{j.run_id}/leaderboard" if lb_path.exists() else None

    body = f"""
<h1>Job <code>{j.job_id}</code></h1>
<div class="card">
  <div><b>Status</b>: {j.status}</div>
  <div><b>Message</b>: {j.message}</div>
  <div><b>set_id</b>: <code>{j.set_id}</code></div>
  <div><b>run_id</b>: <code>{j.run_id}</code></div>
  <div style="margin-top:10px">
    <a href="/">← Back</a>
  </div>
</div>
<div class="card">
  <h2 style="margin:0 0 10px 0">Outputs</h2>
  <ul>
    <li>Export folder: <code>{RESULTS_BASE / j.run_id}</code></li>
    <li>Leaderboard: {f'<a href="{lb_link}">open</a>' if lb_link else '<span class="muted">not generated yet</span>'}</li>
  </ul>
  <div class="muted">Refresh this page while the job is running.</div>
</div>
"""
    return _html_page(f"Job {job_id}", body)


@app.get("/runs/{run_id}/leaderboard", response_class=HTMLResponse)
def run_leaderboard(run_id: str):
    path = RESULTS_BASE / run_id / "leaderboard" / "index.html"
    if not path.exists():
        return HTMLResponse(_html_page("Not found", "<h1>Leaderboard not found</h1>"), status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))

