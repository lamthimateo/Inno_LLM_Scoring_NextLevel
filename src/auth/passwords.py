"""Password hashing helpers.

Wraps ``passlib`` so the rest of the code doesn't care about the algorithm.
We use bcrypt with a sensible cost factor; ``passlib.CryptContext`` makes
it easy to add new schemes later without rehashing the whole user table.
"""

from __future__ import annotations

from passlib.context import CryptContext


# rounds=12 is the passlib default; explicit so a future bump is reviewable.
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``. Salt is included in the output."""

    if not plain:
        raise ValueError("password must not be empty")
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time compare of ``plain`` against the stored ``hashed`` value."""

    if not plain or not hashed:
        return False
    try:
        return _pwd_ctx.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed: str) -> bool:
    """Return True if the hash uses a deprecated scheme or weaker cost factor."""

    return _pwd_ctx.needs_update(hashed)
