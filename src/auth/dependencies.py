"""FastAPI dependencies for authentication and role checks.

Usage::

    @router.get("/admin")
    def admin_only(user: User = Depends(require_role("admin"))):
        ...

    @router.get("/dashboard")
    def dashboard(user: User = Depends(require_login)):
        ...
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.storage.db import get_session
from src.storage.models import User, UserRole


SESSION_USER_KEY = "user_id"


def get_current_user(
    request: Request, session: Session = Depends(get_session)
) -> Optional[User]:
    """Return the logged-in user or ``None`` (no exception)."""

    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        # Stale session cookie — clear it so the user isn't stuck.
        request.session.pop(SESSION_USER_KEY, None)
        return None
    return user


def require_login(
    request: Request, user: Optional[User] = Depends(get_current_user)
) -> User:
    """Force the request to have a logged-in user; otherwise redirect to /auth/login."""

    if user is None:
        # We raise an HTTPException with a Location header so the redirect
        # propagates through FastAPI's exception layer correctly.
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/auth/login?next={request.url.path}"},
        )
    return user


def require_role(*allowed: str | UserRole) -> Callable[[User], User]:
    """Build a dependency that ensures the user has one of ``allowed`` roles."""

    allowed_values = {
        a.value if isinstance(a, UserRole) else str(a).lower() for a in allowed
    }

    def _checker(user: User = Depends(require_login)) -> User:
        if user.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This page requires one of: {', '.join(sorted(allowed_values))}",
            )
        return user

    return _checker


require_admin = require_role(UserRole.ADMIN)
