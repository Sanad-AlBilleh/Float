"""Goal contribution plans (SRS §4.6, Fixture B, AT-11)."""

from datetime import date

import pytest

from app.application import goals
from app.application.context import Actor
from app.application.dashboard import dashboard, forecast
from app.planning.api import GoalPlan, goal_plan, next_cycle_contribution
from app.shared.clock import FixedClock
from app.shared.dates import cycle_for
from tests.conftest import MADRID
from tests.factories import complete_setup, make_user

SEPTEMBER = cycle_for(date(2026, 9, 20), 1)
MARCH = date(2027, 3, 1)


def plan(movements, *, cycle=SEPTEMBER, target=60000, target_date=MARCH):
    return goal_plan(target_cents=target, target_date=target_date, movements=movements, cycle=cycle, allowance_day=1)


def test_fixture_b_plan():
    assert plan([(date(2026, 9, 2), 5000)]) == GoalPlan(6, 10000, 5000, "behind")


def test_protecting_the_plan_clears_the_reserve():
    assert plan([(date(2026, 9, 2), 5000), (date(2026, 9, 20), 5000)]) == GoalPlan(6, 10000, 0, "on_plan")
    assert plan([(date(2026, 9, 2), 13000)]).pending_reserve_cents == 0


def test_fixture_b_october_plan():
    october = cycle_for(date(2026, 10, 5), 1)
    assert plan([(date(2026, 9, 2), 13000)], cycle=october) == GoalPlan(5, 9400, 9400, "behind")


def test_a_passed_target_date_is_overdue_and_reserves_nothing():
    assert plan([], target_date=date(2026, 9, 1)) == GoalPlan(0, 0, 0, "overdue")
    assert plan([], target_date=date(2026, 9, 2)).status == "behind"  # one cycle left: this one


def test_an_auto_reserve_goal_is_on_plan_while_this_cycle_is_reserved_for_it():
    auto = goal_plan(target_cents=60000, target_date=MARCH, movements=[(date(2026, 9, 2), 5000)], cycle=SEPTEMBER,
                     allowance_day=1, auto_reserve=True)
    assert auto == GoalPlan(6, 10000, 5000, "on_plan")  # the €50 pending is held back from safe-to-spend
    assert plan([(date(2026, 9, 2), 5000)]).status == "behind"  # a manual goal is still behind


def test_complete_and_undated_goals_reserve_nothing():
    assert plan([(date(2026, 9, 2), 60000)]).status == "complete"
    assert plan([], target_date=None) == GoalPlan(0, 0, 0, "no_target_date")


def test_a_release_re_reserves_only_this_cycles_plan():
    before_cycle = (date(2026, 8, 20), 5000)
    assert plan([before_cycle, (date(2026, 9, 2), 10000)]).pending_reserve_cents == 0
    released = plan([before_cycle, (date(2026, 9, 2), 10000), (date(2026, 9, 20), -12000)])
    assert (released.planned_cents, released.pending_reserve_cents) == (9167, 9167)  # ceil(€550 / 6)


def test_future_movements_are_ignored():
    assert plan([(date(2026, 9, 21), 5000)]).pending_reserve_cents == 10000


def test_next_cycle_contribution():
    september = plan([(date(2026, 9, 2), 5000)])
    assert next_cycle_contribution(september, target_cents=60000, protected_now_cents=5000) == 10000
    last = plan([], target_date=date(2026, 9, 2))
    assert next_cycle_contribution(last, target_cents=60000, protected_now_cents=0) == 0
    assert next_cycle_contribution(plan([], target_date=None), target_cents=60000, protected_now_cents=0) == 0


@pytest.fixture
def sept20():
    return FixedClock.on(date(2026, 9, 20), MADRID)


def test_auto_reserve_goals_feed_safe_to_spend(conn, sept20):
    user = make_user(conn, sept20)
    complete_setup(conn, sept20, user, tracking_start=date(2026, 9, 1), opening_cents=50000)
    actor = Actor(user.id)
    laptop = goals.add_goal(conn, actor, goals.GoalInput("Laptop", 60000, MARCH, 2, True), sept20)
    goals.add_goal(conn, actor, goals.GoalInput("Trip", 60000, MARCH, 2, False), sept20)  # plan shown, not reserved
    base = dashboard(conn, user.id, sept20).safe
    assert (base.inputs.goal_plan_reserve_cents, base.discretionary_cents) == (10000, 40000)
    goals.move_money(conn, actor, laptop.id, 5000, sept20)
    after = dashboard(conn, user.id, sept20).safe
    assert (after.inputs.goal_plan_reserve_cents, after.discretionary_cents) == (5000, 40000)  # unchanged
    goals.move_money(conn, actor, laptop.id, 8000, sept20)
    assert dashboard(conn, user.id, sept20).safe.discretionary_cents == 37000  # €30 beyond the plan
    assert forecast(conn, user.id, sept20).forecast.next_free_cents == (
        forecast(conn, user.id, sept20).forecast.carry_over_cents + 75000 - 9400)  # ceil(€470 / 5)


def test_movement_dates_decide_which_cycle_they_count_in():
    assert plan([(date(2026, 9, 21), 60000)]).status == "behind"  # tomorrow's protection is not counted yet
    assert plan([(date(2026, 9, 1), 5000)]) == GoalPlan(6, 10000, 5000, "behind")  # payday counts in this cycle
