"""Pure identity rules: usernames, passwords, scrypt hashing, tokens, lockout (FR-01–03, SRS §9)."""

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.shared.errors import ValidationError

USERNAME = re.compile(r"[a-z0-9_]{3,32}")
SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_BYTES, KEY_BYTES = 2**14, 8, 1, 16, 32
LOCKOUT_WINDOW = timedelta(minutes=15)
USERNAME_FAILURE_LIMIT = 5
ADDRESS_FAILURE_LIMIT = 20


def normalize_username(raw: str | None) -> str:
    username = (raw or "").strip().lower()
    if not USERNAME.fullmatch(username):
        raise ValidationError.single("username", "Use 3–32 characters: lowercase letters, digits, or _.")
    return username


def validate_display_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not 1 <= len(name) <= 50:
        raise ValidationError.single("display_name", "Enter a name of 1–50 characters.")
    if not name.isprintable():  # control and invisible characters (NUL, tab, zero-width space…)
        raise ValidationError.single("display_name", "Use letters, numbers, spaces, and punctuation only.")
    return name


def validate_password(raw: str | None, *, field: str = "password") -> str:
    if raw is None or not 10 <= len(raw) <= 128:
        raise ValidationError.single(field, "Use a password of 10–128 characters.")
    return raw


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, n, r, p, salt, expected = encoded.split("$")
        expected_key = base64.b64decode(expected)
        key = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected_key),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected_key)


# Verified against when a username does not exist, so timing does not reveal which usernames exist.
DUMMY_HASH = hash_password("float-timing-equaliser", salt=b"\x00" * SALT_BYTES)


def new_token() -> str:
    """A random 256-bit token, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lock_expiry(failure_times: Sequence[datetime], limit: int) -> datetime | None:
    """When the latest lock ends, or None if there never was one.

    ``limit`` failures within 15 minutes lock the account for 15 minutes from the failure that
    reached the limit (FR-03). Attempts made while locked are not recorded, so they cannot extend it.
    """
    ordered = sorted(failure_times)
    expiry = None
    for last in range(limit - 1, len(ordered)):
        if ordered[last] - ordered[last - limit + 1] < LOCKOUT_WINDOW:
            expiry = ordered[last] + LOCKOUT_WINDOW
    return expiry


def is_locked(failure_times: Sequence[datetime], now: datetime, limit: int) -> bool:
    expiry = lock_expiry(failure_times, limit)
    return expiry is not None and now < expiry
