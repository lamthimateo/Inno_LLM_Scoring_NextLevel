"""Seed initial users at container boot.

Reads:

- ``SEED_ADMIN_USERNAME`` (default ``admin``)
- ``SEED_ADMIN_PASSWORD`` (default ``admin``)
- ``SEED_DEMO_USERS=1``    create author/reviewer demo users for the demo

Idempotent: admin password is left alone if the user already exists.
Demo users (when ``SEED_DEMO_USERS=1``) always get their documented passwords reset.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select

from src.auth.passwords import hash_password
from src.auth.service import ensure_user, get_user_by_username, register_user
from src.storage.db import session_scope
from src.storage.models import User, UserRole


log = logging.getLogger(__name__)


DEFAULT_ADMIN_PASSWORD = "inno-admin"

DEMO_USERS = [
    {"username": "mateo", "password": "mateo1234", "role": UserRole.AUTHOR.value},
    {"username": "jarod", "password": "jarod1234", "role": UserRole.REVIEWER.value},
]

_LEGACY_REVIEWER_USERNAME = "nikoleta"


def _migrate_legacy_demo_reviewer(session) -> None:
    """Rename ``nikoleta`` -> ``jarod`` for DBs seeded before the reviewer rename.

    Must ``flush()`` after rename so :func:`ensure_user` sees the row before
    attempting an insert (otherwise SQLAlchemy issues UPDATE + INSERT on flush).
    """

    jarod = session.scalar(select(User).where(User.username == "jarod"))
    legacy = session.scalar(
        select(User).where(User.username == _LEGACY_REVIEWER_USERNAME)
    )
    if jarod is not None:
        if legacy is not None and legacy.id != jarod.id:
            session.delete(legacy)
            session.flush()
            log.info(
                "seed: removed duplicate legacy user %r (jarod already exists)",
                _LEGACY_REVIEWER_USERNAME,
            )
        return
    if legacy is None:
        return
    legacy.username = "jarod"
    legacy.password_hash = hash_password(_demo_password("jarod"))
    session.flush()
    log.info("seed: renamed demo reviewer %r -> jarod", _LEGACY_REVIEWER_USERNAME)


def _demo_password(username: str) -> str:
    for u in DEMO_USERS:
        if u["username"] == username:
            return u["password"]
    raise KeyError(username)


def _ensure_demo_user(session, *, username: str, password: str, role: str) -> None:
    """Create or update a demo account with a known password (dev convenience)."""

    existing = get_user_by_username(session, username)
    if existing is None:
        register_user(
            session,
            username=username,
            password=password,
            role=role,
        )
        return
    existing.password_hash = hash_password(password)
    existing.role = role


def seed() -> None:
    admin_username = os.environ.get("SEED_ADMIN_USERNAME", "admin").strip().lower() or "admin"
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD) or DEFAULT_ADMIN_PASSWORD

    if admin_password == DEFAULT_ADMIN_PASSWORD:
        log.warning(
            "seed: using DEFAULT admin password %r. Set SEED_ADMIN_PASSWORD in .env.",
            DEFAULT_ADMIN_PASSWORD,
        )

    with session_scope() as session:
        ensure_user(
            session,
            username=admin_username,
            password=admin_password,
            role=UserRole.ADMIN.value,
        )
        log.info("seed: ensured admin user %r", admin_username)

        if os.environ.get("SEED_DEMO_USERS", "").strip() in {"1", "true", "yes"}:
            _migrate_legacy_demo_reviewer(session)
            for u in DEMO_USERS:
                _ensure_demo_user(session, **u)
                log.info("seed: ensured demo user %r role=%s", u["username"], u["role"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    seed()
