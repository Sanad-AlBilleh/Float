"""SRS Fixture A end to end and the conservation invariant (§4.5, AT-19, AT-20, AT-22)."""

from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.application import bills, goals, shared_money
from app.application.dashboard import dashboard, forecast
from app.db.connection import connect
from app.db.migrations import apply_migrations
from app.households.api import SplitEntry, Transfer, balances, simplify
from app.insights.api import preview
from tests.scenarios.flat_3b import build_flat_3b

TODAY = date(2026, 9, 20)


def safe(conn, flat, actor):
    return dashboard(conn, actor.user_id, flat.clock).safe


def test_fixture_a_dashboard_for_ana(conn):
    flat = build_flat_3b(conn)
    view = dashboard(conn, flat.ana.user_id, flat.clock)
    terms = view.safe.inputs
    assert (terms.recorded_balance_cents, terms.personal_bills_cents, terms.household_bill_shares_cents,
            terms.protected_savings_cents, terms.household_payables_cents, terms.goal_plan_reserve_cents) == (
        50000, 12000, 1200, 5000, 1000, 0)
    assert (view.safe.discretionary_cents, view.safe.daily_cents, view.cycle.days_remaining) == (30800, 2800, 11)
    assert (preview(view.safe, 11000).after_daily_cents, preview(view.safe, 35000).after_shortfall_cents) == (1800, 4200)
    assert simplify(balances(conn, household_id=flat.household_id)) == [
        Transfer(flat.carla.user_id, flat.ben.user_id, 4000), Transfer(flat.ana.user_id, flat.ben.user_id, 1000)]


def test_fixture_a_forecast_for_ana(conn):
    flat = build_flat_3b(conn)
    result = forecast(conn, flat.ana.user_id, flat.clock).forecast
    assert (result.pace_cents, result.runway_days, result.run_out_date, result.status, result.carry_over_cents) == (
        1200, 25, date(2026, 10, 15), "on_track", 17600)
    assert (result.lowest_expected.day, result.lowest_expected.expected_cents) == (date(2026, 9, 30), 22600)
    assert result.timeline[-1].conservative_cents == -27800
    assert result.next_daily_cents == 2561


def test_fixture_a_conservation_steps(conn):
    flat = build_flat_3b(conn)
    clock = flat.clock
    phone = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.pay_occurrence(conn, flat.ana, phone.id, phone.version, TODAY, clock)  # step 1
    assert (safe(conn, flat, flat.ana).inputs.recorded_balance_cents, safe(conn, flat, flat.ana).discretionary_cents) == (
        38000, 30800)
    settlement, _ = shared_money.record_settlement(conn, flat.ana, flat.household_id, flat.ana.user_id,
                                                   flat.ben.user_id, 1000, TODAY, clock)  # step 2
    assert safe(conn, flat, flat.ana).discretionary_cents == 30800
    shared_money.confirm_settlement(conn, flat.ben, settlement.id, settlement.version, clock)
    ana = safe(conn, flat, flat.ana)
    assert (ana.inputs.recorded_balance_cents, ana.inputs.household_payables_cents, ana.discretionary_cents) == (
        37000, 0, 30800)
    assert balances(conn, household_id=flat.household_id)[flat.ben.user_id] == 4000
    carla_before = safe(conn, flat, flat.carla).discretionary_cents
    internet = shared_money.get_household_occurrence(conn, flat.carla, flat.internet_occurrence_id)
    shared_money.pay_household_occurrence(conn, flat.carla, internet.id, internet.version, TODAY, clock)  # step 3
    ana = safe(conn, flat, flat.ana)
    assert (ana.inputs.household_bill_shares_cents, ana.inputs.household_payables_cents, ana.discretionary_cents) == (
        0, 1200, 30800)
    assert safe(conn, flat, flat.carla).discretionary_cents == carla_before
    assert safe(conn, flat, flat.carla).inputs.household_payables_cents == 1600
    everyone = tuple(SplitEntry(a.user_id) for a in (flat.ana, flat.ben, flat.carla))
    shared_money.record_expense(conn, flat.ana, flat.household_id, shared_money.ExpenseDraft(
        6000, TODAY, 2, "Dinner", False, "equal", everyone), clock)  # step 4
    assert balances(conn, household_id=flat.household_id)[flat.ana.user_id] == 2800
    ana = dashboard(conn, flat.ana.user_id, clock)
    assert (ana.safe.inputs.household_payables_cents, ana.safe.discretionary_cents) == (0, 26000)
    assert ana.household_receivables_cents == 2800


OPERATIONS = st.lists(st.tuples(st.sampled_from(["personal", "household", "settle", "protect"]),
                                st.integers(0, 2), st.integers(0, 2), st.integers(1, 6000)), min_size=1, max_size=5)


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(OPERATIONS)
def test_conversions_change_discretionary_by_minus_the_change_in_receivables(tmp_path_factory, operations):
    conn = connect(tmp_path_factory.mktemp("conservation") / "db.sqlite3")
    try:
        apply_migrations(conn)
        flat = build_flat_3b(conn)
        clock = flat.clock
        people = [flat.ana, flat.ben, flat.carla]
        laptop = goals.add_goal(conn, flat.ana, goals.GoalInput("Laptop", 60000, date(2027, 3, 1), 2, True), clock)

        def state():
            views = {a.user_id: dashboard(conn, a.user_id, clock) for a in people}
            return {user: (v.safe.discretionary_cents, v.household_receivables_cents) for user, v in views.items()}

        for kind, first, second, amount in operations:
            before = state()
            if kind == "personal":
                open_bills = [o for o in bills.overview(conn, flat.ana, clock).occurrences
                              if o.status in ("reserved", "overdue")]
                if not open_bills:
                    continue
                bills.pay_occurrence(conn, flat.ana, open_bills[0].id, open_bills[0].version, TODAY, clock)
            elif kind == "household":
                payer = people[first]
                open_rows = [o for o in shared_money.household_bills(conn, payer, flat.household_id, clock).occurrences
                             if o.status in ("reserved", "overdue")]
                if not open_rows:
                    continue
                shared_money.pay_household_occurrence(conn, payer, open_rows[0].id, open_rows[0].version, TODAY, clock)
            elif kind == "settle":
                if first == second:
                    continue
                payer, payee = people[first], people[second]
                settlement, _ = shared_money.record_settlement(conn, payer, flat.household_id, payer.user_id,
                                                               payee.user_id, amount, TODAY, clock)
                shared_money.confirm_settlement(conn, payee, settlement.id, settlement.version, clock)
            else:
                pending = safe(conn, flat, flat.ana).inputs.goal_plan_reserve_cents
                if pending == 0:
                    continue
                goals.move_money(conn, flat.ana, laptop.id, min(pending, amount), clock)
            after = state()
            for user in before:
                discretionary_change = after[user][0] - before[user][0]
                receivables_change = after[user][1] - before[user][1]
                assert discretionary_change == -receivables_change, (kind, user, before, after)
    finally:
        conn.close()
