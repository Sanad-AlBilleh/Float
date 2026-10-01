"""Account use cases own their transactions; failed logins are committed before they raise."""

from datetime import timedelta

import pytest

from app.application.accounts import log_in, register_account
from app.identity.api import AuthenticationError, LockedOutError

PASSWORD = "correct horse battery"
MAX_AGE = timedelta(days=14)


def attempt(conn, clock, password):
    return log_in(conn, username="ana", password=password, client_address="10.0.0.1", clock=clock, max_age=MAX_AGE)


def test_registration_returns_a_signed_in_session(conn, clock):
    session, token = register_account(
        conn, username="ana", display_name="Ana", password=PASSWORD, clock=clock, max_age=MAX_AGE
    )
    assert session.user.username == "ana" and token
    assert not conn.in_transaction


def test_failed_login_is_committed_before_it_raises(conn, clock):
    register_account(conn, username="ana", display_name="Ana", password=PASSWORD, clock=clock, max_age=MAX_AGE)
    with pytest.raises(AuthenticationError):
        attempt(conn, clock, "wrong password")
    assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE succeeded = 0").fetchone()[0] == 1
    assert not conn.in_transaction


def test_lockout_raises_its_own_error(conn, clock):
    register_account(conn, username="ana", display_name="Ana", password=PASSWORD, clock=clock, max_age=MAX_AGE)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            attempt(conn, clock, "wrong password")
    with pytest.raises(LockedOutError):
        attempt(conn, clock, PASSWORD)
