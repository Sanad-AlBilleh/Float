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


def test_no_reminder_in_a_first_partial_cycle(conn, clock):
    ben = make_user(conn, clock, "ben")
    complete_setup(conn, clock, ben, tracking_start=date(2026, 9, 20), opening_cents=50000)
    assert not dashboard(conn, ben.id, clock).allowance_reminder


def test_the_dashboard_requires_setup(conn, clock):
    carla = make_user(conn, clock, "carla")
    with pytest.raises(ConflictError):
        dashboard(conn, carla.id, clock)
