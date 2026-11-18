"""Account use cases. Each opens its own transaction (SRS §6.4)."""

from datetime import timedelta

from app.db.connection import Connection
from app.db.unit_of_work import transaction
from app.identity import api as identity
from app.shared.clock import Clock


def register_account(conn: Connection, *, username: str | None, display_name: str | None,
                     password: str | None, clock: Clock, max_age: timedelta,
                     token_secret: str) -> tuple[identity.Session, str]:
    """Create the account and sign it in, in one transaction."""
    with transaction(conn):
        user = identity.register(
            conn, username=username, display_name=display_name, password=password, now=clock.now_utc()
        )
        return identity.start_session(conn, user=user, now=clock.now_utc(), max_age=max_age,
                                      token_secret=token_secret)


def log_in(conn: Connection, *, username: str | None, password: str | None, client_address: str,
           clock: Clock, max_age: timedelta, token_secret: str) -> tuple[identity.Session, str]:
    with transaction(conn):
        outcome = identity.attempt_login(
            conn,
            username=username,
            password=password,
            client_address=client_address,
            now=clock.now_utc(),
            max_age=max_age,
            token_secret=token_secret,
        )
    # Raise only after the commit, so a failed attempt still counts toward throttling (FR-03).
    if outcome.locked:
        raise identity.LockedOutError(outcome.retry_after_minutes)
    if outcome.session is None:
        raise identity.AuthenticationError()
    return outcome.session, outcome.token


def log_out(conn: Connection, *, token: str | None) -> None:
    with transaction(conn):
        identity.logout(conn, token=token)


def change_password(conn: Connection, *, session: identity.Session, current_password: str | None,
                    new_password: str | None, clock: Clock) -> None:
    with transaction(conn):
        identity.change_password(
            conn,
            user_id=session.user.id,
            current_password=current_password,
            new_password=new_password,
            keep_session_id=session.id,
            now=clock.now_utc(),
        )
