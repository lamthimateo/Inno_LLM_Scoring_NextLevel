"""Admin page — read-only view of the model back ends.

Shows the configured Ollama address and the models installed in it, plus
which cloud providers have an API key set (names only, never values).
Admin role required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.adapters.ollama_adapter import ollama_timeout_s
from src.adapters.registry import local_discovery, provider_overview
from src.auth.dependencies import require_admin
from src.storage.models import User
from src.web.templating import render

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse, name="admin.index")
def index(request: Request, user: User = Depends(require_admin)):
    # Always ask Ollama now (not the few-second cache): an admin checking this
    # page wants the current state.
    discovery = local_discovery(fresh=True)
    return render(
        request,
        "admin/index.html",
        current_user=user,
        active_tab="admin",
        ollama=discovery,
        ollama_timeout_s=ollama_timeout_s(),
        providers=provider_overview(),
    )
