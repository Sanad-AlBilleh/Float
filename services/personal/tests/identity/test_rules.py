from datetime import UTC, datetime, timedelta

import pytest

from app.identity.rules import (
    hash_password,
    hash_token,
    is_locked,
    lock_expiry,
    new_token,
    normalize_username,
    validate_display_name,
    validate_password,
    verify_password,
)
from app.shared.errors import ValidationError

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("raw, expected", [("Ana_1", "ana_1"), ("  ben ", "ben"), ("abc", "abc"), ("a" * 32, "a" * 32)])
def test_usernames_are_normalized(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "ab", "a" * 33, "ana!", "ana maria", "ána"])
def test_invalid_usernames_are_rejected(raw):
    with pytest.raises(ValidationError) as error:
        normalize_username(raw)
    assert "username" in error.value.errors


@pytest.mark.parametrize(
    "raw, ok", [("x" * 9, False), ("x" * 10, True), ("x" * 128, True), ("x" * 129, False), (None, False)]
)
def test_password_length_rules(raw, ok):
    if ok:
        assert validate_password(raw) == raw
    else:
        with pytest.raises(ValidationError):
            validate_password(raw)


def test_display_name_is_trimmed_and_bounded():
    assert validate_display_name("  Ana  ") == "Ana"
    for bad in (None, "", " ", "x" * 51):
        with pytest.raises(ValidationError):
            validate_display_name(bad)


def test_scrypt_hash_verifies_and_is_salted():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("scrypt$16384$8$1$") and first != second
    assert verify_password("correct horse", first)
    assert not verify_password("wrong horse", first)
    assert not verify_password("correct horse", "scrypt$broken")


def test_tokens_are_random_and_stored_as_sha256():
    token = new_token()
    assert len(token) >= 43 and token != new_token()
    assert len(hash_token(token)) == 64 and hash_token(token) != token


def test_lockout_counts_failures_inside_the_window_only():
    recent = [NOW - timedelta(minutes=minutes) for minutes in range(4)]
    assert not is_locked(recent, NOW, limit=5)
    assert is_locked(recent + [NOW - timedelta(minutes=14)], NOW, limit=5)
    assert not is_locked(recent + [NOW - timedelta(minutes=15)], NOW, limit=5)


def test_a_lock_lasts_fifteen_minutes_from_the_failure_that_triggered_it():
    failures = [NOW + timedelta(minutes=minutes) for minutes in (0, 1, 2, 3, 14)]
    assert lock_expiry(failures, limit=5) == NOW + timedelta(minutes=29)
    assert is_locked(failures, NOW + timedelta(minutes=14, seconds=30), limit=5)
    assert is_locked(failures, NOW + timedelta(minutes=28, seconds=59), limit=5)
    assert not is_locked(failures, NOW + timedelta(minutes=29), limit=5)
    assert lock_expiry(failures[:4], limit=5) is None


@pytest.mark.parametrize("raw", ["\x00abc", "Ana\tB", "Ana\u200b"])
def test_display_names_reject_control_and_invisible_characters(raw):
    with pytest.raises(ValidationError) as error:
        validate_display_name(raw)
    assert error.value.errors == {"display_name": "Use letters, numbers, spaces, and punctuation only."}
