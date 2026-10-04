"""Household bills: reserved shares, payment into a shared expense, and undo (FR-25–26, AT-18)."""

from datetime import date

import pytest

from app.application import shared_money
from app.application.dashboard import dashboard
from app.households.api import SplitEntry, balances
from app.ledger.api import list_transactions
from app.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from app.shared.recurrence import Rule
from tests.scenarios.flat_3b import UTILITIES, build_flat_3b


@pytest.fixture
def flat(conn):
    return build_flat_3b(conn)


def terms(conn, flat, actor):
    return dashboard(conn, actor.user_id, flat.clock).safe.inputs


def internet(conn, flat, actor):
    return next(o for o in shared_money.household_bills(conn, actor, flat.household_id, flat.clock).occurrences
                if o.id == flat.internet_occurrence_id)


def test_each_participant_reserves_their_share(conn, flat):
    for actor in (flat.ana, flat.ben, flat.carla):
        assert terms(conn, flat, actor).household_bill_shares_cents == 1200
    row = internet(conn, flat, flat.ben)
    assert (row.status, row.my_share_cents) == ("reserved", 1200)


def test_templates_cannot_be_exact_or_start_in_the_past(conn, flat):
    everyone = tuple(SplitEntry(a.user_id, None) for a in (flat.ana, flat.ben, flat.carla))
    for method, anchor in (("exact", date(2026, 9, 30)), ("equal", date(2026, 9, 19))):
        with pytest.raises(ValidationError):
            shared_money.add_household_bill(conn, flat.ana, flat.household_id, shared_money.HouseholdBillInput(
                "Water", 3000, UTILITIES, Rule("monthly", 1, anchor), method, everyone), flat.clock)
    with pytest.raises(PermissionDeniedError):
        shared_money.add_household_bill(conn, flat.ben, flat.household_id, shared_money.HouseholdBillInput(
            "Water", 3000, UTILITIES, Rule("monthly", 1, date(2026, 9, 30)), "equal", everyone), flat.clock)


def test_editing_an_unpaid_amount_changes_every_share(conn, flat):
    row = internet(conn, flat, flat.carla)
    shared_money.edit_household_occurrence(conn, flat.carla, row.id, row.version, 4500, row.due_date, flat.clock)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1500


def test_paying_turns_shares_into_payables_and_undo_restores_everything(conn, flat):
    before = {a.user_id: terms(conn, flat, a) for a in (flat.ana, flat.ben, flat.carla)}
    row = internet(conn, flat, flat.carla)
    expense = shared_money.pay_household_occurrence(conn, flat.carla, row.id, row.version, date(2026, 9, 20),
                                                    flat.clock)
    assert expense.payer_user_id == flat.carla.user_id and expense.amount_cents == 3600
    assert set(expense.shares.values()) == {1200}
    ana = terms(conn, flat, flat.ana)
    assert (ana.household_bill_shares_cents, ana.household_payables_cents) == (0, 2200)  # €10 groceries + €12
    assert internet(conn, flat, flat.ana).status == "paid"
    with pytest.raises(ConflictError):
        shared_money.pay_household_occurrence(conn, flat.ben, row.id, row.version, date(2026, 9, 20), flat.clock)
    with pytest.raises(ConflictError, match="Bills tab"):
        shared_money.edit_expense(conn, flat.carla, expense.id, expense.version,
                                  shared_money.ExpenseDraft(1, date(2026, 9, 20), UTILITIES, "x", False, "equal",
                                                            (SplitEntry(flat.carla.user_id),)), flat.clock)
    paid = internet(conn, flat, flat.carla)
    with pytest.raises(PermissionDeniedError):
        shared_money.undo_household_payment(conn, flat.ana, paid.id, paid.version, flat.clock)
    shared_money.undo_household_payment(conn, flat.carla, paid.id, paid.version, flat.clock)
    after = {a.user_id: terms(conn, flat, a) for a in (flat.ana, flat.ben, flat.carla)}
    assert after == before
    assert not [t for t in list_transactions(conn, user_id=flat.carla.user_id) if t.note == "Internet"]


def test_skipping_reserves_nothing(conn, flat):
    row = internet(conn, flat, flat.ben)
    shared_money.skip_household_occurrence(conn, flat.ben, row.id, row.version, flat.clock, skipped=True)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 0
    skipped = internet(conn, flat, flat.ben)
    shared_money.skip_household_occurrence(conn, flat.ben, skipped.id, skipped.version, flat.clock, skipped=False)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1200


def test_ending_a_bill_lets_participants_leave(conn, flat):
    from app.application import households

    series = shared_money.household_bills(conn, flat.ana, flat.household_id, flat.clock).series[0]
    with pytest.raises(PermissionDeniedError):
        shared_money.end_household_bill(conn, flat.ben, series.id, series.version, flat.clock)
    shared_money.end_household_bill(conn, flat.ana, series.id, series.version, flat.clock)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 0  # the 28 Sep bill was due later: removed
    with pytest.raises(ConflictError, match="owe"):
        households.leave(conn, flat.carla, flat.household_id, flat.clock)  # still owes for electricity
    assert balances(conn, household_id=flat.household_id)[flat.carla.user_id] == -4000


def add(conn, flat, *people, anchor=date(2026, 10, 1), method="equal", values=None):
    values = values or [None] * len(people)
    return shared_money.add_household_bill(conn, flat.ana, flat.household_id, shared_money.HouseholdBillInput(
        "Rent", 60000, UTILITIES, Rule("monthly", 1, anchor), method,
        tuple(SplitEntry(p.user_id, v) for p, v in zip(people, values))), flat.clock)


def test_a_bill_due_on_payday_belongs_to_the_next_cycle(conn, flat):
    add(conn, flat, flat.ana, flat.ben)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1200  # only the Internet share


def test_an_exact_template_is_refused_even_when_it_adds_up(conn, flat):
    with pytest.raises(ValidationError) as error:
        add(conn, flat, flat.ana, flat.ben, method="exact", values=[30000, 30000])
    assert "split_method" in error.value.errors


def test_only_participants_change_or_pay_a_bill(conn, flat):
    add(conn, flat, flat.ana, flat.ben, anchor=date(2026, 9, 25))
    rent = next(o for o in shared_money.household_bills(conn, flat.carla, flat.household_id, flat.clock).occurrences
                if o.name == "Rent")
    assert (rent.participant, rent.my_share_cents) == (False, 0)
    for action in (
        lambda: shared_money.pay_household_occurrence(conn, flat.carla, rent.id, rent.version, date(2026, 9, 20),
                                                      flat.clock),
        lambda: shared_money.skip_household_occurrence(conn, flat.carla, rent.id, rent.version, flat.clock,
                                                       skipped=True),
        lambda: shared_money.edit_household_occurrence(conn, flat.carla, rent.id, rent.version, 100, rent.due_date,
                                                       flat.clock),
    ):
        with pytest.raises(PermissionDeniedError):
            action()


def test_budgets_count_shares_not_the_cash_fronted(conn, flat):
    from app.application import budgets

    _, rows = budgets.budgets(conn, flat.ana, flat.clock)
    by_id = {row.category.id: row.consumption_cents for row in rows}
    assert by_id[1] == 18800 + 1000  # her groceries plus her €10 share, not the €30 she fronted
    assert by_id[UTILITIES] == 3000  # her share of Ben's electricity


def test_a_zero_percent_participant_is_explained_not_a_crash(conn, flat):
    """Review finding 3: the schema needs a weight of at least 1, so 0% must be refused with a message."""
    with pytest.raises(ValidationError) as error:
        add(conn, flat, flat.ana, flat.ben, method="percentage", values=[10000, 0])
    assert "split" in error.value.errors and "above zero" in error.value.errors["split"]


def test_nobody_leaves_while_sharing_an_unpaid_bill(conn, clock):
    """Review finding 4: an overdue bill of an ended series must be paid or skipped before a sharer leaves."""
    from app.application import households
    from tests.households.conftest import flat as make_flat

    household, ana, ben, carla = make_flat.__wrapped__(conn, clock)
    everyone = tuple(SplitEntry(a.user_id) for a in (ana, ben, carla))
    series = shared_money.add_household_bill(conn, ana, household.id, shared_money.HouseholdBillInput(
        "Internet", 3600, UTILITIES, Rule("monthly", 1, date(2026, 9, 30)), "equal", everyone), clock)
    clock.advance(days=1)  # 1 October: the 30 September bill is overdue
    shared_money.end_household_bill(conn, ana, series.id, series.version, clock)
    with pytest.raises(ConflictError, match="Internet"):
        households.leave(conn, ben, household.id, clock)
    overdue = next(o for o in shared_money.household_bills(conn, ben, household.id, clock).occurrences
                   if o.status == "overdue")
    shared_money.skip_household_occurrence(conn, ben, overdue.id, overdue.version, clock, skipped=True)
    households.leave(conn, ben, household.id, clock)
