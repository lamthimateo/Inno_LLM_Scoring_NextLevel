"""Seed initial users at container boot.

Reads:

- ``SEED_ADMIN_USERNAME`` (default ``admin``)
- ``SEED_ADMIN_PASSWORD`` (default ``admin``)
- ``SEED_DEMO_USERS=1``    create author/reviewer demo users for the demo

Idempotent: if a username already exists, the password is left alone.
"""

from __future__ import annotations

import logging
import os

from src.auth.service import ensure_user
from src.storage.db import session_scope
from src.storage.models import UserRole


log = logging.getLogger(__name__)


DEFAULT_ADMIN_PASSWORD = "inno-admin"

DEMO_USERS = [
    {"username": "mateo", "password": "mateo1234", "role": UserRole.AUTHOR.value},
    {"username": "nikoleta", "password": "nikoleta1234", "role": UserRole.REVIEWER.value},
]


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
            for u in DEMO_USERS:
                ensure_user(session, **u)
                log.info("seed: ensured demo user %r role=%s", u["username"], u["role"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    seed()
