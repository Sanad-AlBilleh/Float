"""Identity use cases on an open connection: accounts, login throttling, and sessions (FR-01–03).

Callers own the transaction. ``attempt_login`` reports a failure in its return value instead of
raising, so the caller can commit the recorded attempt before telling the person it failed;
raising inside the transaction would roll the attempt back and defeat the throttle.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.identity import repository
from app.identity.rules import (
    ADDRESS_FAILURE_LIMIT,
    DUMMY_HASH,
    LOCKOUT_WINDOW,
    USERNAME_FAILURE_LIMIT,
    hash_password,
    hash_token,
    is_locked,
    new_token,
    normalize_username,
    validate_display_name,
    validate_password,
    verify_password,
)
from app.shared.clock import from_utc_text
from app.shared.errors import FloatError, NotFoundError, ValidationError

ATTEMPT_RETENTION = timedelta(hours=24)
TOUCH_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str


@dataclass(frozen=True)
class Session:
    id: int
    user: User
    csrf_token: str


@dataclass(frozen=True)
class LoginOutcome:
    """``session`` and ``token`` are set on success; ``locked`` is true when throttling refused the attempt."""

    session: Session | None
    token: str | None
    locked: bool = False


class AuthenticationError(FloatError):
    def __init__(self) -> None:
        super().__init__("Incorrect username or password.")


class LockedOutError(FloatError):
    def __init__(self) -> None:
        super().__init__("Too many attempts. Try again in 15 minutes.")


def _user(row: sqlite3.Row) -> User:
    return User(row["id"], row["username"], row["display_name"])


def register(conn: sqlite3.Connection, *, username: str | None, display_name: str | None,
             password: str | None, now: datetime) -> User:
    errors: dict[str, str] = {}
    clean: dict[str, str] = {}
    for field, check, raw in (
        ("username", normalize_username, username),
        ("display_name", validate_display_name, display_name),
        ("password", validate_password, password),
    ):
        try:
            clean[field] = check(raw)
        except ValidationError as error:
            errors.update(error.errors)
    if "username" in clean and repository.find_user_by_username(conn, clean["username"]) is not None:
        errors["username"] = "That username is taken."
    if errors:
        raise ValidationError(errors)
    try:
        user_id = repository.insert_user(
            conn,
            username=clean["username"],
            display_name=clean["display_name"],
            password_hash=hash_password(clean["password"]),
            now=now,
        )
    except sqlite3.IntegrityError:
        raise ValidationError.single("username", "That username is taken.") from None
    return User(user_id, clean["username"], clean["display_name"])


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = repository.get_user(conn, user_id)
    if row is None:
        raise NotFoundError("No such user.")
    return _user(row)


def start_session(conn: sqlite3.Connection, *, user: User, now: datetime, max_age: timedelta) -> tuple[Session, str]:
    """Create a session and return it with the raw token; only the token's hash is stored."""
    token, csrf_token = new_token(), new_token()
    session_id = repository.insert_session(
        conn,
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=csrf_token,
        now=now,
        expires_at=now + max_age,
    )
    return Session(session_id, user, csrf_token), token


def attempt_login(conn: sqlite3.Connection, *, username: str | None, password: str | None,
                  client_address: str, now: datetime, max_age: timedelta) -> LoginOutcome:
    key = (username or "").strip().lower()[:64]
    repository.prune_attempts(conn, before=now - ATTEMPT_RETENTION)
    since = now - LOCKOUT_WINDOW
    username_locked = is_locked(
        repository.username_failures(conn, username_key=key, since=since), now, USERNAME_FAILURE_LIMIT
    )
    address_locked = is_locked(
        repository.address_failures(conn, client_address=client_address, since=since), now, ADDRESS_FAILURE_LIMIT
    )
    if username_locked or address_locked:
        return LoginOutcome(None, None, locked=True)  # not recorded, so a lock cannot be extended forever
    row = repository.find_user_by_username(conn, key)
    matches = verify_password(password or "", row["password_hash"] if row is not None else DUMMY_HASH)
    succeeded = row is not None and matches
    repository.record_attempt(conn, username_key=key, client_address=client_address, now=now, succeeded=succeeded)
    if not succeeded:
        return LoginOutcome(None, None)
    session, token = start_session(conn, user=_user(row), now=now, max_age=max_age)
    return LoginOutcome(session, token)


def resolve_session(conn: sqlite3.Connection, *, token: str | None, now: datetime, idle: timedelta) -> Session | None:
    """The live session for ``token``, or None. Expired sessions are deleted as they are found."""
    if not token:
        return None
    row = repository.find_session(conn, hash_token(token))
    if row is None:
        return None
    last_seen = from_utc_text(row["last_seen_at"])
    if now >= from_utc_text(row["expires_at"]) or now - last_seen >= idle:
        repository.delete_session(conn, row["session_id"])
        return None
    if now - last_seen >= TOUCH_INTERVAL:
        repository.touch_session(conn, row["session_id"], now)
    user = User(row["user_id"], row["username"], row["display_name"])
    return Session(row["session_id"], user, row["csrf_token"])


def logout(conn: sqlite3.Connection, *, token: str | None) -> None:
    if token:
        repository.delete_session_by_token_hash(conn, hash_token(token))


def change_password(conn: sqlite3.Connection, *, user_id: int, current_password: str | None,
                    new_password: str | None, keep_session_id: int, now: datetime) -> None:
    row = repository.get_user(conn, user_id)
    if row is None:
        raise NotFoundError("No such user.")
    errors: dict[str, str] = {}
    if not verify_password(current_password or "", row["password_hash"]):
        errors["current_password"] = "That is not your current password."
    try:
        validate_password(new_password, field="new_password")
    except ValidationError as error:
        errors.update(error.errors)
    if errors:
        raise ValidationError(errors)
    repository.update_password(conn, user_id=user_id, password_hash=hash_password(new_password), now=now)
    repository.delete_other_sessions(conn, user_id=user_id, keep_session_id=keep_session_id)
