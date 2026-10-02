"""Savings goals with protect and release movements (FR-14, AT-10)."""

import sqlite3
from datetime import date

import pytest

from app.ledger.api import get_balance
from app.planning.api import (
    archive_goal,
    create_goal,
    get_goal,
    get_obligations,
    list_goals,
    move,
    movements,
    update_goal,
)
from app.shared.dates import cycle_for
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from tests.factories import complete_setup, make_user

START = date(2026, 9, 1)
TODAY = date(2026, 9, 30)


@pytest.fixture
def ana(conn, clock):
    user = make_user(conn, clock)
    complete_setup(conn, clock, user, tracking_start=START, opening_cents=50000)
    return user


@pytest.fixture
def fund(conn, clock, ana):
    return create_goal(conn, user_id=ana.id, name="Emergency fund", target_cents=20000, now=clock.now_utc())


def protected(conn, user):
    return get_obligations(conn, user_id=user.id, cycle=cycle_for(TODAY, 1)).protected_savings_cents


def test_protecting_reserves_money_without_touching_the_balance(conn, clock, ana, fund):
    goal = move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=5000, moved_on=TODAY, note="", now=clock.now_utc())
    assert goal.protected_cents == 5000 and protected(conn, ana) == 5000
    assert get_balance(conn, user_id=ana.id, as_of=TODAY) == 50000
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=-2000, moved_on=TODAY, note="", now=clock.now_utc())
    assert protected(conn, ana) == 3000
    assert movements(conn, user_id=ana.id, goal_id=fund.id) == [(TODAY, 5000), (TODAY, -2000)]


@pytest.mark.parametrize("delta", [-1, 20001, 0])
def test_protected_money_stays_between_zero_and_the_target(conn, clock, ana, fund, delta):
    with pytest.raises(ValidationError) as error:
        move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=delta, moved_on=TODAY, note="", now=clock.now_utc())
    assert "amount" in error.value.errors


def test_the_whole_target_can_be_protected(conn, clock, ana, fund):
    assert move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=20000, moved_on=TODAY, note="",
                now=clock.now_utc()).protected_cents == 20000


def test_protected_savings_may_exceed_cash(conn, clock, ana):
    big = create_goal(conn, user_id=ana.id, name="Car", target_cents=100000, now=clock.now_utc())
    move(conn, user_id=ana.id, goal_id=big.id, delta_cents=60000, moved_on=TODAY, note="", now=clock.now_utc())
    assert protected(conn, ana) == 60000  # more than the €500 balance: a shortfall, not an invented transfer


def test_movements_are_append_only(conn, clock, ana, fund):
    move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=5000, moved_on=TODAY, note="", now=clock.now_utc())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE goal_movements SET delta_cents = 1")


def test_archiving_releases_everything(conn, clock, ana, fund):
    move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=5000, moved_on=TODAY, note="", now=clock.now_utc())
    archive_goal(conn, user_id=ana.id, goal_id=fund.id, version=fund.version, moved_on=TODAY, now=clock.now_utc())
    assert protected(conn, ana) == 0 and list_goals(conn, user_id=ana.id) == []
    assert movements(conn, user_id=ana.id, goal_id=fund.id)[-1] == (TODAY, -5000)
    with pytest.raises(ConflictError):
        move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=100, moved_on=TODAY, note="", now=clock.now_utc())


def test_goals_validate_every_field(conn, clock, ana):
    with pytest.raises(ValidationError) as error:
        create_goal(conn, user_id=ana.id, name="", target_cents=0, priority=4, now=clock.now_utc())
    assert set(error.value.errors) == {"name", "target", "priority"}


def test_the_target_cannot_drop_below_what_is_protected(conn, clock, ana, fund):
    move(conn, user_id=ana.id, goal_id=fund.id, delta_cents=5000, moved_on=TODAY, note="", now=clock.now_utc())
    current = get_goal(conn, user_id=ana.id, goal_id=fund.id)
    with pytest.raises(ValidationError) as error:
        update_goal(conn, user_id=ana.id, goal_id=fund.id, version=current.version, name="Fund", target_cents=4999,
                    target_date=None, priority=1, auto_reserve=True)
    assert "target" in error.value.errors
    changed = update_goal(conn, user_id=ana.id, goal_id=fund.id, version=current.version, name="Fund",
                          target_cents=5000, target_date=date(2027, 3, 1), priority=1, auto_reserve=True)
    assert (changed.name, changed.target_cents, changed.target_date, changed.priority, changed.auto_reserve) == (
        "Fund", 5000, date(2027, 3, 1), 1, True)
    with pytest.raises(ConflictError):
        update_goal(conn, user_id=ana.id, goal_id=fund.id, version=current.version, name="Fund", target_cents=6000,
                    target_date=None, priority=1, auto_reserve=True)


def test_other_peoples_goals_are_not_found(conn, clock, ana, fund):
    ben = make_user(conn, clock, "ben")
    with pytest.raises(NotFoundError):
        get_goal(conn, user_id=ben.id, goal_id=fund.id)
    with pytest.raises(NotFoundError):
        move(conn, user_id=ben.id, goal_id=fund.id, delta_cents=100, moved_on=TODAY, note="", now=clock.now_utc())
