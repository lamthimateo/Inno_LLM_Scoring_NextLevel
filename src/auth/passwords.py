"""Password hashing helpers (bcrypt)."""

from __future__ import annotations

import re

import bcrypt


ROUNDS = 12
_BCRYPT_COST_RE = re.compile(r"^\$2[aby]\$(\d+)\$")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``. Salt is included in the output."""

    if not plain:
        raise ValueError("password must not be empty")
    digest = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=ROUNDS))
    return digest.decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time compare of ``plain`` against the stored ``hashed`` value."""

    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Return True if the hash uses a weaker cost factor than :data:`ROUNDS`."""

    match = _BCRYPT_COST_RE.match(hashed or "")
    if not match:
        return True
    return int(match.group(1)) < ROUNDS
