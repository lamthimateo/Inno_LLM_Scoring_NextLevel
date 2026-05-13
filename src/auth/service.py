"""High-level auth/account workflows.

Pure functions over a SQLAlchemy ``Session``. The HTTP layer (router.py)
translates results into responses; this module never knows about Request /
cookies / templates so it can be reused from scripts or tests.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import PasswordResetToken, User, UserRole

from .passwords import hash_password, needs_rehash, verify_password


log = logging.getLogger(__name__)


USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_\-.]{1,30}[a-z0-9])?$")
MIN_PASSWORD_LEN = 8
RESET_TOKEN_TTL = timedelta(hours=1)


# Pre-computed dummy hash used in ``authenticate`` so the missing-user path
# still spends time hashing. This prevents timing attacks from leaking
# whether a username exists.
_DUMMY_PASSWORD_HASH: Optional[str] = None


def _dummy_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password("dummy-burn-only-not-a-real-password")
    return _DUMMY_PASSWORD_HASH


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(ValueError):
    """Base class for expected auth failures (bad input, conflict, etc.)."""


class InvalidCredentials(AuthError):
    pass


class UsernameTaken(AuthError):
    pass


class EmailTaken(AuthError):
    pass


class WeakPassword(AuthError):
    pass


class InvalidUsername(AuthError):
    pass


class InvalidResetToken(AuthError):
    pass


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _normalize_username(raw: str) -> str:
    username = (raw or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise InvalidUsername(
            "Username must be 3-32 chars, lowercase letters/digits/underscore/dash/dot, "
            "starting + ending with a letter or digit."
        )
    return username


def _normalize_email(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    email = raw.strip().lower()
    if not email:
        return None
    # Cheap RFC-ish validation; we're not delivering email anyway.
    if "@" not in email or len(email) > 254:
        raise AuthError(f"Invalid email: {raw!r}")
    return email


def _validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LEN:
        raise WeakPassword(
            f"Password must be at least {MIN_PASSWORD_LEN} characters."
        )


def _normalize_role(raw: Optional[str]) -> str:
    if raw is None:
        return UserRole.AUTHOR.value
    candidate = raw.strip().lower()
    if candidate not in {r.value for r in UserRole}:
        raise AuthError(f"Unknown role: {raw!r}")
    return candidate


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    if not username:
        return None
    norm = username.strip().lower()
    return session.execute(
        select(User).where(func.lower(User.username) == norm)
    ).scalar_one_or_none()


def get_user_by_id(session: Session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_user(
    session: Session,
    *,
    username: str,
    password: str,
    email: Optional[str] = None,
    role: Optional[str] = None,
    is_active: bool = True,
) -> User:
    """Create a new user, hashing the password."""

    normalized_username = _normalize_username(username)
    normalized_email = _normalize_email(email)
    _validate_password(password)
    normalized_role = _normalize_role(role)

    if get_user_by_username(session, normalized_username) is not None:
        raise UsernameTaken(f"Username {normalized_username!r} is already taken.")

    if normalized_email is not None:
        clash = session.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        ).scalar_one_or_none()
        if clash is not None:
            raise EmailTaken(f"Email {normalized_email!r} is already registered.")

    user = User(
        username=normalized_username,
        email=normalized_email,
        password_hash=hash_password(password),
        role=normalized_role,
        is_active=is_active,
    )
    session.add(user)
    session.flush()
    log.info("user.registered username=%s role=%s id=%s", user.username, user.role, user.id)
    return user


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def authenticate(session: Session, *, username: str, password: str) -> User:
    """Return the user matching ``username``/``password`` or raise.

    Transparently rehashes the password if the stored hash uses a deprecated
    scheme. The error message intentionally does not distinguish "no such
    user" from "bad password" to avoid username enumeration.
    """

    if not username or not password:
        raise InvalidCredentials("Invalid username or password.")

    user = get_user_by_username(session, username)
    if user is None or not user.is_active:
        # Burn a hash anyway so timing leaks less info.
        verify_password(password, _dummy_hash())
        raise InvalidCredentials("Invalid username or password.")

    if not verify_password(password, user.password_hash):
        raise InvalidCredentials("Invalid username or password.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.flush()

    return user


# ---------------------------------------------------------------------------
# Change password (self-serve, requires current password)
# ---------------------------------------------------------------------------


def change_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentials("Current password is incorrect.")
    if current_password == new_password:
        raise WeakPassword("New password must differ from the current one.")
    _validate_password(new_password)
    user.password_hash = hash_password(new_password)
    session.flush()
    log.info("user.password_changed user_id=%s", user.id)


# ---------------------------------------------------------------------------
# Password reset (token-based; email is logged for the demo)
# ---------------------------------------------------------------------------


def create_password_reset_request(
    session: Session, *, username_or_email: str
) -> Optional[str]:
    """Issue a single-use reset token for the user, or return None silently.

    Returning None on no-such-user avoids account enumeration. The token is
    logged (not returned to the HTTP response) so the demo flow is "admin
    grabs the link from the server log and shares it".
    """

    if not username_or_email:
        return None

    needle = username_or_email.strip().lower()
    user = session.execute(
        select(User).where(
            (func.lower(User.username) == needle) | (func.lower(User.email) == needle)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
    session.add(
        PasswordResetToken(token=token, user_id=user.id, expires_at=expires_at)
    )
    session.flush()
    log.warning(
        "password_reset.requested username=%s token=%s expires=%s "
        "(use the URL /auth/reset?token=<token>)",
        user.username,
        token,
        expires_at.isoformat(),
    )
    return token


def reset_password_with_token(
    session: Session, *, token: str, new_password: str
) -> User:
    if not token:
        raise InvalidResetToken("Missing reset token.")
    _validate_password(new_password)

    row = session.get(PasswordResetToken, token)
    if row is None:
        raise InvalidResetToken("Unknown or expired reset token.")
    if row.used_at is not None:
        raise InvalidResetToken("This reset token has already been used.")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise InvalidResetToken("Reset token has expired.")

    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise InvalidResetToken("Account is disabled.")

    user.password_hash = hash_password(new_password)
    row.used_at = datetime.now(timezone.utc)
    session.flush()
    log.info("user.password_reset user_id=%s", user.id)
    return user


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------


def ensure_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: str = UserRole.ADMIN.value,
    email: Optional[str] = None,
) -> User:
    """Idempotent: create the user if missing, otherwise return existing.

    Used by ``src.web.seed`` so ``docker compose up`` always lands you with
    a usable admin without clobbering an existing password if one is set.
    """

    existing = get_user_by_username(session, username)
    if existing is not None:
        return existing
    return register_user(
        session,
        username=username,
        password=password,
        email=email,
        role=role,
    )
