"""Unit tests for the auth service layer (no HTTP)."""

from __future__ import annotations

import pytest

from src.auth.passwords import hash_password, needs_rehash, verify_password
from src.auth.service import (
    EmailTaken,
    InvalidCredentials,
    InvalidResetToken,
    InvalidUsername,
    UsernameTaken,
    WeakPassword,
    authenticate,
    change_password,
    create_password_reset_request,
    ensure_user,
    register_user,
    reset_password_with_token,
)
from src.storage.models import UserRole


def test_hash_and_verify_roundtrip():
    h = hash_password("hunter22")
    assert h != "hunter22"
    assert verify_password("hunter22", h) is True
    assert verify_password("wrong", h) is False


def test_verify_rejects_empty():
    h = hash_password("hunter22")
    assert verify_password("", h) is False
    assert verify_password("hunter22", "") is False


def test_needs_rehash_returns_false_for_fresh_hash():
    assert needs_rehash(hash_password("hunter22")) is False


# ---------------------------------------------------------------------------


def test_register_user_creates_row(session):
    user = register_user(session, username="alice", password="strongpass1")
    assert user.id is not None
    assert user.username == "alice"
    assert user.role == UserRole.AUTHOR.value
    assert verify_password("strongpass1", user.password_hash)


def test_register_user_normalizes_username(session):
    user = register_user(session, username="  ALICE  ", password="strongpass1")
    assert user.username == "alice"


def test_register_user_rejects_short_username(session):
    with pytest.raises(InvalidUsername):
        register_user(session, username="al", password="strongpass1")


def test_register_user_rejects_weak_password(session):
    with pytest.raises(WeakPassword):
        register_user(session, username="alice", password="short")


def test_register_user_rejects_duplicate_username(session):
    register_user(session, username="alice", password="strongpass1")
    with pytest.raises(UsernameTaken):
        register_user(session, username="alice", password="otherpass1")


def test_register_user_rejects_duplicate_email(session):
    register_user(session, username="alice", password="strongpass1", email="a@x.com")
    with pytest.raises(EmailTaken):
        register_user(session, username="bob", password="strongpass1", email="A@X.COM")


def test_authenticate_returns_user_on_match(session):
    register_user(session, username="alice", password="strongpass1")
    user = authenticate(session, username="alice", password="strongpass1")
    assert user.username == "alice"


def test_authenticate_rejects_wrong_password(session):
    register_user(session, username="alice", password="strongpass1")
    with pytest.raises(InvalidCredentials):
        authenticate(session, username="alice", password="bad")


def test_authenticate_rejects_unknown_user(session):
    with pytest.raises(InvalidCredentials):
        authenticate(session, username="ghost", password="strongpass1")


def test_authenticate_rejects_inactive_user(session):
    user = register_user(session, username="alice", password="strongpass1")
    user.is_active = False
    session.flush()
    with pytest.raises(InvalidCredentials):
        authenticate(session, username="alice", password="strongpass1")


def test_change_password_updates_hash(session):
    user = register_user(session, username="alice", password="strongpass1")
    change_password(
        session, user=user, current_password="strongpass1", new_password="newerpass2"
    )
    assert verify_password("newerpass2", user.password_hash)


def test_change_password_rejects_wrong_current(session):
    user = register_user(session, username="alice", password="strongpass1")
    with pytest.raises(InvalidCredentials):
        change_password(
            session, user=user, current_password="bad", new_password="newerpass2"
        )


def test_change_password_rejects_unchanged(session):
    user = register_user(session, username="alice", password="strongpass1")
    with pytest.raises(WeakPassword):
        change_password(
            session,
            user=user,
            current_password="strongpass1",
            new_password="strongpass1",
        )


def test_password_reset_full_flow(session):
    register_user(session, username="alice", password="strongpass1")
    token = create_password_reset_request(session, username_or_email="alice")
    assert token is not None

    user = reset_password_with_token(session, token=token, new_password="brandnew1")
    assert verify_password("brandnew1", user.password_hash)


def test_password_reset_token_is_single_use(session):
    register_user(session, username="alice", password="strongpass1")
    token = create_password_reset_request(session, username_or_email="alice")

    reset_password_with_token(session, token=token, new_password="brandnew1")
    with pytest.raises(InvalidResetToken):
        reset_password_with_token(session, token=token, new_password="another1")


def test_password_reset_for_unknown_user_returns_none(session):
    assert create_password_reset_request(session, username_or_email="ghost") is None


def test_ensure_user_is_idempotent(session):
    a = ensure_user(session, username="bob", password="strongpass1")
    b = ensure_user(session, username="bob", password="differentpass2")
    assert a.id == b.id
    # Existing user's password is NOT overwritten on second call.
    assert verify_password("strongpass1", b.password_hash)
