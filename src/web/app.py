"""FastAPI application — v0.2.0 placeholder.

Day 1 only contains a single liveness endpoint so ``uvicorn`` can boot the
container. Days 2-5 progressively replace this with auth, Questions tab,
Runs tab, and Results tab.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


app = FastAPI(title="Inno LLM Scoring", version="0.2.0-dev")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"/>"
        "<title>Inno LLM Scoring</title>"
        "<style>body{font-family:system-ui;margin:40px;max-width:640px;color:#0f172a}"
        "code{background:#f1f5f9;padding:2px 6px;border-radius:6px}</style></head>"
        "<body><h1>Inno LLM Scoring — Day 1</h1>"
        "<p>Docker + Postgres + SQLAlchemy + Alembic are up. "
        "Auth and the Questions / Results tabs land in Days 2-5.</p>"
        "<p>Health check: <code>GET /healthz</code></p>"
        "</body></html>"
    )
