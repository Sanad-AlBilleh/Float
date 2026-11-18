"""SRS Fixture A on the households side, and the conservation invariants (§4.5, AT-19, AT-20, AT-22).

The end-to-end safe-to-spend invariant needs both services; it is the cross-seam integration test's job.
Here: the household terms each member's dashboard gets, and that money only moves between members.
"""

from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.application import shared_money, summary
from app.households.api import SplitEntry, Transfer, balances, simplify
from tests import dbtest
from tests.fakes import FakePersonal
from tests.scenarios.flat_3b import TODAY, build_flat_3b

CYCLE_END, HORIZON = date(2026, 10, 1), date(2026, 11, 1)


def position(conn, actor):
    return summary.position(conn, user_id=actor.user_id, window_end=CYCLE_END, horizon_end=HORIZON)


def test_fixture_a_household_terms(conn, personal):
    flat = build_flat_3b(conn, personal)
    ana = position(conn, flat.ana)
    assert (ana.bill_shares_cents, ana.payables_cents, ana.receivables_cents) == (1200, 1000, 0)
    assert [(c["due_date"], c["amount_cents"]) for c in ana.commitments] == [
        (date(2026, 9, 28), 1200), (date(2026, 10, 28), 1200)]
    assert position(conn, flat.ben).receivables_cents == 5000
    assert simplify(balances(conn, household_id=flat.household_id)) == [
        Transfer(flat.carla.user_id, flat.ben.user_id, 4000), Transfer(flat.ana.user_id, flat.ben.user_id, 1000)]


def test_fixture_a_conservation_steps(conn, personal):
    flat = build_flat_3b(conn, personal)
    clock = flat.clock
    settlement, _ = shared_money.record_settlement(conn, personal, flat.ana, flat.household_id, flat.ana.user_id,
                                                   flat.ben.user_id, 1000, TODAY, clock)
    assert position(conn, flat.ana).payables_cents == 1000  # pending: nothing moves yet
    shared_money.confirm_settlement(conn, personal, flat.ben, settlement.id, settlement.version, clock)
    assert position(conn, flat.ana).payables_cents == 0
    assert balances(conn, household_id=flat.household_id)[flat.ben.user_id] == 4000
    internet = shared_money.get_household_occurrence(conn, flat.carla, flat.internet_occurrence_id)
    shared_money.pay_household_occurrence(conn, personal, flat.carla, internet.id, internet.version, TODAY, clock)
    ana = position(conn, flat.ana)
    assert (ana.bill_shares_cents, ana.payables_cents) == (0, 1200)  # a reserved share became a payable
    assert position(conn, flat.carla).payables_cents == 1600
    everyone = tuple(SplitEntry(a.user_id) for a in (flat.ana, flat.ben, flat.carla))
    shared_money.record_expense(conn, personal, flat.ana, flat.household_id, shared_money.ExpenseDraft(
        6000, TODAY, 2, "Dinner", False, "equal", everyone), clock)
    assert balances(conn, household_id=flat.household_id)[flat.ana.user_id] == 2800
    assert position(conn, flat.ana).receivables_cents == 2800


OPERATIONS = st.lists(st.tuples(st.sampled_from(["expense", "bill", "settle"]), st.integers(0, 2), st.integers(0, 2),
                                st.integers(1, 6000)), min_size=1, max_size=5)


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(OPERATIONS)
def test_balances_always_sum_to_zero_and_match_the_ledger_rows(conn, operations):
    """Whatever happens, household money only moves between members, and every euro a member fronted or
    settled is a ledger row in the personal service."""
    dbtest.reset(conn)
    personal = FakePersonal()
    flat = build_flat_3b(conn, personal)
    people = [flat.ana, flat.ben, flat.carla]
    for kind, first, second, amount in operations:
        payer = people[first]
        if kind == "expense":
            shared_money.record_expense(conn, personal, payer, flat.household_id, shared_money.ExpenseDraft(
                amount, TODAY, 2, "Snacks", False, "equal", tuple(SplitEntry(a.user_id) for a in people)), flat.clock)
        elif kind == "bill":
            rows = [o for o in shared_money.household_bills(conn, personal, payer, flat.household_id,
                                                            flat.clock).occurrences if o.status in ("reserved", "overdue")]
            if rows:
                shared_money.pay_household_occurrence(conn, personal, payer, rows[0].id, rows[0].version, TODAY,
                                                      flat.clock)
        elif first != second:
            payee = people[second]
            settlement, _ = shared_money.record_settlement(conn, personal, payer, flat.household_id, payer.user_id,
                                                           payee.user_id, amount, TODAY, flat.clock)
            shared_money.confirm_settlement(conn, personal, payee, settlement.id, settlement.version, flat.clock)
        nets = balances(conn, household_id=flat.household_id)
        assert sum(nets.values()) == 0
        fronted = sum(e.amount_cents for e in shared_money.list_expenses(conn, flat.ana, flat.household_id))
        assert fronted == sum(r.amount_cents for r in personal.rows.values() if r.origin == "shared")
