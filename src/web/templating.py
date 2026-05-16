"""Shared Jinja2 setup.

Wraps :class:`fastapi.templating.Jinja2Templates` so every route gets the
same globals (app version, current user resolution, flashes, csrf_token,
url_for, etc.) without each view having to remember to pass them.

The polished design-system templates (under ``src/web/templates/``) use
Flask-style ``url_for(endpoint, **kwargs)`` calls. Since this app is
FastAPI, we provide a small dispatch table that maps endpoint names to
URL patterns; this keeps the templates portable and avoids hardcoding
absolute paths inside every template.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src.storage.models import User

import importlib.metadata


def _read_app_version() -> str:
    try:
        return importlib.metadata.version("inno-llm-scoring-nextlevel")
    except importlib.metadata.PackageNotFoundError:
        return "0.2.0-dev"


APP_VERSION = _read_app_version()


# ---------------------------------------------------------------------------
# url_for: Flask-style endpoint resolution
# ---------------------------------------------------------------------------

# Map of ``endpoint_name`` -> ``(path_template, [path_param_names])``.
# ``path_template`` is a ``str.format`` pattern; any kwargs that do not
# correspond to a path param are appended as a query string.
_ROUTES: dict[str, tuple[str, list[str]]] = {
    "home": ("/", []),
    "login": ("/auth/login", []),
    "logout": ("/auth/logout", []),
    "signup": ("/auth/signup", []),
    "forgot_password": ("/auth/forgot", []),
    "reset_password": ("/auth/reset", []),
    "change_password": ("/auth/change-password", []),
    "account": ("/account", []),
    "questions.list": ("/questions", []),
    "questions.import_view": ("/questions/import", []),
    "questions.preview": ("/questions/preview", []),
    "questions.detail": ("/questions/{set_id}", ["set_id"]),
    "questions.edit": ("/questions/{set_id}/edit", ["set_id"]),
    "questions.edit_one": ("/questions/{set_id}/{qid}", ["set_id", "qid"]),
    "questions.diff": ("/questions/{set_id}/{qid}/diff", ["set_id", "qid"]),
    "questions.validate": ("/questions/{set_id}/validate", ["set_id"]),
    "questions.submit_review": ("/questions/{set_id}/submit-review", ["set_id"]),
    "questions.approve": ("/questions/{set_id}/approve", ["set_id"]),
    "questions.lock": ("/questions/{set_id}/lock", ["set_id"]),
    "questions.revert": ("/questions/{set_id}/revert", ["set_id"]),
    "runs.list": ("/runs", []),
    "runs.new": ("/runs/new", []),
    "runs.create": ("/runs/new", []),
    "runs.detail": ("/runs/{run_id}", ["run_id"]),
    "runs.detail_fragment": ("/runs/{run_id}/status", ["run_id"]),
    "runs.cancel": ("/runs/{run_id}/cancel", ["run_id"]),
    "results.list": ("/results", []),
    "results.leaderboard": ("/results/{run_id}", ["run_id"]),
    "results.export": ("/results/export.csv", []),
    "results.run_csv": ("/results/{run_id}/export.csv", ["run_id"]),
    "results.run_json": ("/results/{run_id}/export.json", ["run_id"]),
}


def url_for(endpoint: str, **kwargs: Any) -> str:
    """Flask-compatible URL builder for our Jinja templates.

    Special case: ``url_for('static', filename='css/app.css')`` returns
    ``/static/css/app.css`` to match the design-system templates.
    """

    if endpoint == "static":
        filename = kwargs.pop("filename", kwargs.pop("path", ""))
        return f"/static/{filename}"

    route = _ROUTES.get(endpoint)
    if route is None:
        return "#"
    template, path_params = route
    fmt_kwargs: dict[str, Any] = {}
    for name in path_params:
        value = kwargs.pop(name, "")
        fmt_kwargs[name] = quote(str(value), safe="")
    path = template.format(**fmt_kwargs)

    query = {k: v for k, v in kwargs.items() if v not in (None, "", False)}
    if query:
        return f"{path}?{urlencode(query)}"
    return path


def _csrf_token() -> str:
    """Stub CSRF token.

    The current app uses signed session cookies + SameSite=Lax; no CSRF
    token is wired up yet. Templates ask for one defensively
    (``csrf_token()``) so we return an empty string. Hooks for a real
    CSRF token can be added here later without touching templates.
    """

    return ""


def _signup_enabled() -> bool:
    """Whether self-service signup is enabled.

    True in this build — the school project assumes open signup on the
    dev/demo deployment. Wire to config/env later if needed.
    """

    return True


# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------


templates = Jinja2Templates(directory="src/web/templates")
templates.env.globals["app_version"] = APP_VERSION
templates.env.globals["url_for"] = url_for
templates.env.globals["csrf_token"] = _csrf_token
templates.env.globals["signup_enabled"] = _signup_enabled()


def _build_flashes(request: Request) -> list[dict[str, str]]:
    """Translate ``?ok=...`` / ``?error=...`` query params into design-system flash dicts."""

    flashes: list[dict[str, str]] = []
    ok = request.query_params.get("ok")
    err = request.query_params.get("error")
    warn = request.query_params.get("warn")
    info = request.query_params.get("info")
    if ok:
        flashes.append({"category": "success", "message": ok})
    if err:
        flashes.append({"category": "error", "message": err})
    if warn:
        flashes.append({"category": "warn", "message": warn})
    if info:
        flashes.append({"category": "info", "message": info})
    return flashes


def render(
    request: Request,
    template: str,
    *,
    current_user: Optional[User] = None,
    active_tab: Optional[str] = None,
    status_code: int = 200,
    **extra: Any,
):
    """Render a template with the standard global context applied.

    ``error=...`` / ``ok=...`` kwargs are auto-promoted into the
    ``flashes`` list so the design-system alert component picks them up
    even when the route renders inline (no redirect). They remain
    available under their original names for templates that still read
    them directly.
    """

    flashes = _build_flashes(request)
    inline_error = extra.get("error")
    inline_ok = extra.get("ok")
    if inline_error:
        flashes.append({"category": "error", "message": str(inline_error)})
    if inline_ok:
        flashes.append({"category": "success", "message": str(inline_ok)})

    ctx: dict[str, Any] = {
        "current_user": current_user,
        "active_tab": active_tab,
        "flashes": flashes,
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
