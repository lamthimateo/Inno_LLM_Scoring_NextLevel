"""Shared Jinja2 setup.

Wraps :class:`fastapi.templating.Jinja2Templates` so every route gets the
same globals (app version, current user resolution, etc.) without each view
having to remember to pass them.
"""

from __future__ import annotations

from typing import Any, Optional

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


templates = Jinja2Templates(directory="src/web/templates")
templates.env.globals["app_version"] = APP_VERSION


def render(
    request: Request,
    template: str,
    *,
    current_user: Optional[User] = None,
    active_tab: Optional[str] = None,
    status_code: int = 200,
    **extra: Any,
):
    """Render a template with the standard global context applied."""

    ctx: dict[str, Any] = {
        "current_user": current_user,
        "active_tab": active_tab,
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
