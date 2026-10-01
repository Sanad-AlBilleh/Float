"""Day 1 dashboard: recorded balance, the cycle, and the allowance reminder (FR-27 partial, FR-28, AT-21)."""

from datetime import date

import pytest

from app.application.dashboard import dashboard
from app.shared.errors import ConflictError
from tests.factories import add_expense, add_income, complete_setup, make_user

START = date(2026, 9, 1)


@pytest.fixture
def ana(conn, clock):
    user = make_user(conn, clock)
    complete_setup(conn, clock, user, tracking_start=START, opening_cents=10000)
    return user


def test_dashboard_shows_balance_cycle_and_planned_allowance(conn, clock, ana):
    add_income(conn, clock, ana, 75000, START)
    add_expense(conn, clock, ana, 2540, date(2026, 9, 20))
    view = dashboard(conn, ana.id, clock)
    assert view.recorded_balance_cents == 82460
    assert (view.cycle.next_allowance, view.cycle.days_remaining) == (date(2026, 10, 1), 1)
    assert view.planned_allowance_cents == 75000
    assert not view.allowance_reminder


def test_planned_allowance_never_counts_until_recorded(conn, clock, ana):
    view = dashboard(conn, ana.id, clock)
    assert view.recorded_balance_cents == 10000 and view.allowance_reminder
    add_income(conn, clock, ana, 5000, date(2026, 9, 10), source="other")
    assert dashboard(conn, ana.id, clock).allowance_reminder  # unrelated income does not clear it
    add_income(conn, clock, ana, 75000, date(2026, 9, 12))
    assert not dashboard(conn, ana.id, clock).allowance_reminder


def test_no_reminder_when_setup_said_the_allowance_is_already_counted(conn, clock):
    ben = make_user(conn, clock, "ben")
    complete_setup(conn, clock, ben, tracking_start=START, opening_cents=85000, allowance_included=True)
    assert not dashboard(conn, ben.id, clock).allowance_reminder  # setting up on payday (finding 3)
    clock.advance(days=1)  # 1 October: a new cycle and a new allowance to record
    assert dashboard(conn, ben.id, clock).allowance_reminder


def test_a_partial_first_cycle_still_reminds_when_the_allowance_is_not_counted(conn, clock):
    carla = make_user(conn, clock, "carla")
    complete_setup(conn, clock, carla, tracking_start=date(2026, 9, 20), opening_cents=50000)
    assert dashboard(conn, carla.id, clock).allowance_reminder
    dina = make_user(conn, clock, "dina")
    complete_setup(conn, clock, dina, tracking_start=date(2026, 9, 20), opening_cents=50000,
                   allowance_included=True)
    assert not dashboard(conn, dina.id, clock).allowance_reminder


def test_a_balance_below_zero_is_flagged(conn, clock, ana):
    assert not dashboard(conn, ana.id, clock).below_zero
    add_expense(conn, clock, ana, 10001, date(2026, 9, 20))
    view = dashboard(conn, ana.id, clock)
    assert view.recorded_balance_cents == -1 and view.below_zero


def test_the_dashboard_requires_setup(conn, clock):
    erin = make_user(conn, clock, "erin")
    with pytest.raises(ConflictError):
        dashboard(conn, erin.id, clock)
