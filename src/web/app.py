"""FastAPI application entrypoint.

Day 2 wires:

- ``SessionMiddleware`` (signed cookies; secret from ``SESSION_SECRET``)
- Static asset mount at ``/static``
- Auth router (login / logout / signup / forgot / reset / change-password)
- Home dashboard at ``/`` (requires login; redirects to /auth/login otherwise)

Days 3-5 progressively add the Questions tab, Runs tab, and Results tab.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.auth.dependencies import get_current_user
from src.auth.router import router as auth_router
from src.storage.models import User
from src.web.routes.questions import router as questions_router
from src.web.routes.runs import router as runs_router
from src.web.templating import APP_VERSION, render


SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
SESSION_COOKIE_NAME = "inno_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # one week


app = FastAPI(title="Inno LLM Scoring", version=APP_VERSION)


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=False,  # set True behind a TLS proxy in production
)


# Static assets live next to the project so the same files are reachable in
# both dev (uvicorn with --reload) and the Docker image.
app.mount("/static", StaticFiles(directory="static"), name="static")


app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(runs_router)


@app.get("/results")
def results_alias():
    """Friendly alias for /runs — the nav uses /runs but /results is intuitive too."""
    return RedirectResponse(url="/runs", status_code=307)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)
    return render(request, "home.html", current_user=user)
