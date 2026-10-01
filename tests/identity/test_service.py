"""Registration, login throttling, and sessions (FR-01–03, AT-01, AT-02)."""

from datetime import timedelta

import pytest

from app.identity.api import (
    attempt_login,
    change_password,
    get_user,
    logout,
    register,
    resolve_session,
    start_session,
)
from app.identity.rules import hash_token, verify_password
from app.shared.clock import from_utc_text
from app.shared.errors import ValidationError

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"
IDLE = timedelta(hours=48)
MAX_AGE = timedelta(days=14)


@pytest.fixture
def ana(conn, clock):
    return register(conn, username="Ana", display_name="Ana", password=PASSWORD, now=clock.now_utc())


def login(conn, clock, username="ana", password=PASSWORD, address="10.0.0.1"):
    return attempt_login(
        conn,
        username=username,
        password=password,
        client_address=address,
        now=clock.now_utc(),
        max_age=MAX_AGE,
    )


def resolve(conn, clock, token):
    return resolve_session(conn, token=token, now=clock.now_utc(), idle=IDLE)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def last_seen(conn, session_id):
    row = conn.execute("SELECT last_seen_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return from_utc_text(row[0])


def test_register_stores_a_lowercase_username(conn, ana):
    assert (ana.username, ana.display_name) == ("ana", "Ana")
    assert get_user(conn, ana.id) == ana


def test_usernames_are_unique_regardless_of_case(conn, clock, ana):
    with pytest.raises(ValidationError) as error:
        register(conn, username="ANA", display_name="Other", password=PASSWORD, now=clock.now_utc())
    assert error.value.errors == {"username": "That username is taken."}


def test_registration_reports_every_invalid_field_at_once(conn, clock):
    with pytest.raises(ValidationError) as error:
        register(conn, username="a!", display_name="", password="short", now=clock.now_utc())
    assert set(error.value.errors) == {"username", "display_name", "password"}


def test_passwords_are_stored_only_as_scrypt_hashes(conn, ana):
    stored = conn.execute("SELECT password_hash FROM users WHERE id = ?", (ana.id,)).fetchone()[0]
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert verify_password(PASSWORD, stored)


def test_login_creates_a_session_that_stores_only_the_token_hash(conn, clock, ana):
    outcome = login(conn, clock)
    assert outcome.session.user == ana and not outcome.locked
    row = conn.execute("SELECT token_hash, expires_at FROM sessions WHERE id = ?", (outcome.session.id,)).fetchone()
    assert row["token_hash"] == hash_token(outcome.token) != outcome.token
    assert from_utc_text(row["expires_at"]) == clock.now_utc() + MAX_AGE


def test_wrong_password_and_unknown_username_look_identical(conn, clock, ana):
    wrong = login(conn, clock, password="not the password")
    unknown = login(conn, clock, username="nobody")
    assert (wrong.session, wrong.token, wrong.locked) == (unknown.session, unknown.token, unknown.locked)
    assert wrong.session is None and not wrong.locked


def test_the_timing_dummy_password_never_signs_anyone_in(conn, clock):
    outcome = login(conn, clock, username="ghost", password="float-timing-equaliser")
    assert outcome.session is None and not outcome.locked


def test_five_failures_lock_the_username_for_fifteen_minutes(conn, clock, ana):
    for _ in range(5):
        assert login(conn, clock, password="wrong password").session is None
    refused = login(conn, clock)  # even the right password is refused while locked
    assert refused.locked and refused.session is None
    clock.advance(minutes=15, seconds=1)
    assert login(conn, clock).session is not None


def test_a_successful_login_resets_the_username_count(conn, clock, ana):
    for _ in range(4):
        login(conn, clock, password="wrong password")
    assert login(conn, clock).session is not None
    for _ in range(4):
        login(conn, clock, password="wrong password")
    assert not login(conn, clock).locked


def test_twenty_failures_from_one_address_block_that_address(conn, clock, ana):
    for number in range(20):
        login(conn, clock, username=f"guess{number}", password="wrong password", address="10.9.9.9")
    assert login(conn, clock, address="10.9.9.9").locked
    assert login(conn, clock, address="10.0.0.2").session is not None


def test_attempts_during_a_lockout_are_not_recorded(conn, clock, ana):
    for _ in range(5):
        login(conn, clock, password="wrong password")
    before = count(conn, "login_attempts")
    for _ in range(3):
        login(conn, clock, password="wrong password")
    assert count(conn, "login_attempts") == before


def test_attempts_older_than_a_day_are_pruned(conn, clock, ana):
    login(conn, clock, password="wrong password")
    clock.advance(hours=25)
    login(conn, clock)
    assert count(conn, "login_attempts") == 1


def test_active_sessions_resolve_and_refresh_last_seen_once_a_minute(conn, clock, ana):
    outcome = login(conn, clock)
    started = clock.now_utc()
    clock.advance(seconds=30)
    assert resolve(conn, clock, outcome.token) == outcome.session
    assert last_seen(conn, outcome.session.id) == started
    clock.advance(minutes=2)
    assert resolve(conn, clock, outcome.token) == outcome.session
    assert last_seen(conn, outcome.session.id) == clock.now_utc()


def test_idle_sessions_expire_and_are_deleted(conn, clock, ana):
    outcome = login(conn, clock)
    clock.advance(hours=48)
    assert resolve(conn, clock, outcome.token) is None
    assert count(conn, "sessions") == 0


def test_sessions_end_after_fourteen_days_even_when_active(conn, clock, ana):
    outcome = login(conn, clock)
    for _ in range(13):
        clock.advance(days=1)
        assert resolve(conn, clock, outcome.token) is not None
    clock.advance(days=1)
    assert resolve(conn, clock, outcome.token) is None


def test_missing_or_unknown_tokens_resolve_to_nothing(conn, clock):
    assert resolve(conn, clock, None) is None
    assert resolve(conn, clock, "not-a-real-token") is None


def test_logout_deletes_the_session(conn, clock, ana):
    outcome = login(conn, clock)
    logout(conn, token=outcome.token)
    assert resolve(conn, clock, outcome.token) is None


def test_changing_the_password_requires_the_current_one(conn, clock, ana):
    outcome = login(conn, clock)
    with pytest.raises(ValidationError) as error:
        change_password(
            conn,
            user_id=ana.id,
            current_password="not my password",
            new_password=NEW_PASSWORD,
            keep_session_id=outcome.session.id,
            now=clock.now_utc(),
        )
    assert "current_password" in error.value.errors


def test_changing_the_password_ends_every_other_session(conn, clock, ana):
    phone, laptop = login(conn, clock), login(conn, clock)
    change_password(
        conn,
        user_id=ana.id,
        current_password=PASSWORD,
        new_password=NEW_PASSWORD,
        keep_session_id=laptop.session.id,
        now=clock.now_utc(),
    )
    assert resolve(conn, clock, phone.token) is None
    assert resolve(conn, clock, laptop.token) == laptop.session
    assert login(conn, clock, password=NEW_PASSWORD).session is not None
    assert login(conn, clock).session is None


def test_each_session_gets_its_own_token_and_csrf_token(conn, clock, ana):
    first, first_token = start_session(conn, user=ana, now=clock.now_utc(), max_age=MAX_AGE)
    second, second_token = start_session(conn, user=ana, now=clock.now_utc(), max_age=MAX_AGE)
    assert first_token != second_token
    assert first.csrf_token != second.csrf_token
