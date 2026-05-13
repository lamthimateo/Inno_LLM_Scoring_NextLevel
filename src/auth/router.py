"""HTTP routes for authentication and account management.

All endpoints are server-rendered (Jinja2 + form posts + redirects). Designed
to work with any browser, no JS required for the auth flow itself.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from src.storage.db import get_session
from src.storage.models import User
from src.web.templating import render

from .dependencies import SESSION_USER_KEY, get_current_user, require_login
from .service import (
    AuthError,
    InvalidCredentials,
    InvalidResetToken,
    InvalidUsername,
    UsernameTaken,
    WeakPassword,
    EmailTaken,
    authenticate,
    change_password,
    create_password_reset_request,
    register_user,
    reset_password_with_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    next: Optional[str] = None,
    user: Optional[User] = Depends(get_current_user),
) -> HTMLResponse:
    if user is not None:
        return RedirectResponse(url=next or "/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "auth/login.html", error=None, next=next or "")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        user = authenticate(session, username=username, password=password)
    except InvalidCredentials as exc:
        session.rollback()
        return render(
            request,
            "auth/login.html",
            error=str(exc),
            next=next,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    session.commit()
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(url=next or "/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request):
    request.session.pop(SESSION_USER_KEY, None)
    return RedirectResponse(
        url="/auth/login?ok=Signed+out.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


@router.get("/signup", response_class=HTMLResponse)
def signup_form(
    request: Request, user: Optional[User] = Depends(get_current_user)
) -> HTMLResponse:
    if user is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "auth/signup.html", error=None, form_values={})


@router.post("/signup")
def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    email: str = Form(""),
    session: Session = Depends(get_session),
):
    form_values = {"username": username, "email": email}
    if password != password_confirm:
        return render(
            request,
            "auth/signup.html",
            error="Passwords do not match.",
            form_values=form_values,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = register_user(
            session,
            username=username,
            password=password,
            email=email or None,
        )
    except (
        InvalidUsername,
        UsernameTaken,
        EmailTaken,
        WeakPassword,
        AuthError,
    ) as exc:
        session.rollback()
        return render(
            request,
            "auth/signup.html",
            error=str(exc),
            form_values=form_values,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session.commit()
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(
        url="/?ok=Welcome+to+Inno+LLM+Scoring.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Forgot / reset password
# ---------------------------------------------------------------------------


@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request) -> HTMLResponse:
    return render(request, "auth/forgot_password.html", ok=None, error=None)


@router.post("/forgot")
def forgot_submit(
    request: Request,
    username_or_email: str = Form(...),
    session: Session = Depends(get_session),
):
    create_password_reset_request(session, username_or_email=username_or_email)
    session.commit()
    # Always show the same message to avoid leaking which usernames exist.
    return render(
        request,
        "auth/forgot_password.html",
        ok=(
            "If that account exists, a reset link has been generated. "
            "Check the server log for the link."
        ),
        error=None,
    )


@router.get("/reset", response_class=HTMLResponse)
def reset_form(request: Request, token: str = "") -> HTMLResponse:
    if not token:
        return RedirectResponse(
            url="/auth/forgot?error=Missing+reset+token.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return render(request, "auth/reset_password.html", token=token, error=None)


@router.post("/reset")
def reset_submit(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    session: Session = Depends(get_session),
):
    if new_password != new_password_confirm:
        return render(
            request,
            "auth/reset_password.html",
            token=token,
            error="Passwords do not match.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        reset_password_with_token(session, token=token, new_password=new_password)
    except (InvalidResetToken, WeakPassword) as exc:
        session.rollback()
        return render(
            request,
            "auth/reset_password.html",
            token=token,
            error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session.commit()
    return RedirectResponse(
        url="/auth/login?ok=Password+reset.+You+can+log+in+now.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Change password (logged in)
# ---------------------------------------------------------------------------


@router.get("/change-password", response_class=HTMLResponse)
def change_password_form(
    request: Request, user: User = Depends(require_login)
) -> HTMLResponse:
    return render(
        request, "auth/change_password.html", current_user=user, ok=None, error=None
    )


@router.post("/change-password")
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    if new_password != new_password_confirm:
        return render(
            request,
            "auth/change_password.html",
            current_user=user,
            ok=None,
            error="New passwords do not match.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        change_password(
            session,
            user=user,
            current_password=current_password,
            new_password=new_password,
        )
    except (InvalidCredentials, WeakPassword) as exc:
        session.rollback()
        return render(
            request,
            "auth/change_password.html",
            current_user=user,
            ok=None,
            error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session.commit()
    return RedirectResponse(
        url="/auth/change-password?ok=Password+updated.",
        status_code=status.HTTP_303_SEE_OTHER,
    )
