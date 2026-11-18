"""Setup writes Ledger and Planning settings atomically, once (FR-05)."""

from datetime import date

import pytest

from app.application import setup as setup_use_cases
from app.application.context import Actor
from app.application.setup import SetupInput, complete_setup, is_setup_complete, update_planned_allowance
from app.ledger.api import get_settings as ledger_settings
from app.planning.api import get_settings as planning_settings
from app.shared.errors import ConflictError, ValidationError
from tests.factories import make_user

START = date(2026, 9, 1)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_setup_writes_both_domains_and_an_audit_event(conn, clock):
    ana = make_user(conn, clock)
    complete_setup(conn, Actor(ana.id, "req-1"), SetupInput(START, -2500, 1, 75000, True), clock)
    assert is_setup_complete(conn, ana.id)
    assert planning_settings(conn, ana.id).opening_includes_allowance
    assert ledger_settings(conn, ana.id).opening_balance_cents == -2500
    assert planning_settings(conn, ana.id).allowance_day == 1
    event = conn.execute("SELECT entity_type, action, request_id FROM audit_events").fetchone()
    assert tuple(event) == ("setup", "complete", "req-1")
    assert count(conn, "transactions") == 0  # setup never creates income (FR-05)


def test_setup_is_all_or_nothing(conn, clock, monkeypatch):
    ana = make_user(conn, clock)

    def fail(*args, **kwargs):
        raise RuntimeError("planning write failed")

    monkeypatch.setattr(setup_use_cases.planning, "save_settings", fail)
    with pytest.raises(RuntimeError):
        complete_setup(conn, Actor(ana.id), SetupInput(START, 0, 1, 75000), clock)
    assert ledger_settings(conn, ana.id) is None
    assert count(conn, "audit_events") == 0
    assert not is_setup_complete(conn, ana.id)


def test_setup_reports_every_invalid_field(conn, clock):
    ana = make_user(conn, clock)
    with pytest.raises(ValidationError) as error:
        complete_setup(conn, Actor(ana.id), SetupInput(date(2026, 10, 1), 0, 0, 0), clock)
    assert set(error.value.errors) == {"tracking_start", "allowance_day", "planned_allowance"}


def test_setup_happens_only_once(conn, clock):
    ana = make_user(conn, clock)
    complete_setup(conn, Actor(ana.id), SetupInput(START, 0, 1, 75000), clock)
    with pytest.raises(ConflictError):
        complete_setup(conn, Actor(ana.id), SetupInput(START, 999, 5, 1000), clock)
    assert ledger_settings(conn, ana.id).opening_balance_cents == 0


def test_only_the_planned_allowance_changes_later(conn, clock):
    ana = make_user(conn, clock)
    complete_setup(conn, Actor(ana.id), SetupInput(START, 0, 1, 75000), clock)
    update_planned_allowance(conn, Actor(ana.id), 80000, clock)
    assert planning_settings(conn, ana.id).planned_allowance_cents == 80000
    actions = [row[0] for row in conn.execute("SELECT action FROM audit_events ORDER BY id")]
    assert actions == ["complete", "update"]


def test_setup_can_start_a_monthly_savings_plan(conn, clock):
    """Student request, 4 October: setup asks how much to save each month and reserves it every cycle."""
    from app.application.context import Actor
    from app.application.dashboard import dashboard
    from app.application.setup import SetupInput, complete_setup
    from app.planning.api import list_goals
    from tests.factories import make_user

    user = make_user(conn, clock, "saver")
    complete_setup(conn, Actor(user.id), SetupInput(date(2026, 9, 1), 50000, 1, 75000, True, 10000), clock)
    [goal] = list_goals(conn, user_id=user.id)
    assert (goal.name, goal.target_cents, goal.auto_reserve) == ("Monthly savings", 120000, True)
    assert dashboard(conn, user.id, clock).safe.inputs.goal_plan_reserve_cents == 10000
