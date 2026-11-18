"""Household bills: reserved shares, payment into a shared expense, and undo (FR-25–26, AT-18).

The "terms" are what this service reports to the personal service for safe-to-spend (/internal position)."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.application import shared_money, summary
from app.households.api import SplitEntry, balances
from app.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from app.shared.recurrence import Rule
from tests.scenarios.flat_3b import UTILITIES, build_flat_3b


@pytest.fixture
def flat(conn, personal):
    return build_flat_3b(conn, personal)


def terms(conn, flat, actor):
    """The household terms of the actor's safe-to-spend for the cycle ending 1 October."""
    position = summary.position(conn, user_id=actor.user_id, window_end=date(2026, 10, 1),
                                horizon_end=date(2026, 11, 1))
    return SimpleNamespace(household_bill_shares_cents=position.bill_shares_cents,
                           household_payables_cents=position.payables_cents)


def internet(conn, personal, flat, actor):
    return next(o for o in shared_money.household_bills(conn, personal, actor, flat.household_id, flat.clock).occurrences
                if o.id == flat.internet_occurrence_id)


def test_each_participant_reserves_their_share(conn, personal, flat):
    for actor in (flat.ana, flat.ben, flat.carla):
        assert terms(conn, flat, actor).household_bill_shares_cents == 1200
    row = internet(conn, personal, flat, flat.ben)
    assert (row.status, row.my_share_cents) == ("reserved", 1200)


def test_templates_cannot_be_exact_or_start_in_the_past(conn, personal, flat):
    everyone = tuple(SplitEntry(a.user_id, None) for a in (flat.ana, flat.ben, flat.carla))
    for method, anchor in (("exact", date(2026, 9, 30)), ("equal", date(2026, 9, 19))):
        with pytest.raises(ValidationError):
            shared_money.add_household_bill(conn, personal, flat.ana, flat.household_id, shared_money.HouseholdBillInput(
                "Water", 3000, UTILITIES, Rule("monthly", 1, anchor), method, everyone), flat.clock)
    with pytest.raises(PermissionDeniedError):
        shared_money.add_household_bill(conn, personal, flat.ben, flat.household_id, shared_money.HouseholdBillInput(
            "Water", 3000, UTILITIES, Rule("monthly", 1, date(2026, 9, 30)), "equal", everyone), flat.clock)


def test_editing_an_unpaid_amount_changes_every_share(conn, personal, flat):
    row = internet(conn, personal, flat, flat.carla)
    shared_money.edit_household_occurrence(conn, flat.carla, row.id, row.version, 4500, row.due_date, flat.clock)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1500


def test_paying_turns_shares_into_payables_and_undo_restores_everything(conn, personal, flat):
    before = {a.user_id: terms(conn, flat, a) for a in (flat.ana, flat.ben, flat.carla)}
    row = internet(conn, personal, flat, flat.carla)
    expense = shared_money.pay_household_occurrence(conn, personal, flat.carla, row.id, row.version, date(2026, 9, 20),
                                                    flat.clock)
    assert expense.payer_user_id == flat.carla.user_id and expense.amount_cents == 3600
    assert set(expense.shares.values()) == {1200}
    ana = terms(conn, flat, flat.ana)
    assert (ana.household_bill_shares_cents, ana.household_payables_cents) == (0, 2200)  # €10 groceries + €12
    assert internet(conn, personal, flat, flat.ana).status == "paid"
    with pytest.raises(ConflictError):
        shared_money.pay_household_occurrence(conn, personal, flat.ben, row.id, row.version, date(2026, 9, 20), flat.clock)
    with pytest.raises(ConflictError, match="Bills tab"):
        shared_money.edit_expense(conn, personal, flat.carla, expense.id, expense.version,
                                  shared_money.ExpenseDraft(1, date(2026, 9, 20), UTILITIES, "x", False, "equal",
                                                            (SplitEntry(flat.carla.user_id),)), flat.clock)
    paid = internet(conn, personal, flat, flat.carla)
    with pytest.raises(PermissionDeniedError):
        shared_money.undo_household_payment(conn, personal, flat.ana, paid.id, paid.version, flat.clock)
    shared_money.undo_household_payment(conn, personal, flat.carla, paid.id, paid.version, flat.clock)
    after = {a.user_id: terms(conn, flat, a) for a in (flat.ana, flat.ben, flat.carla)}
    assert after == before
    assert not [t for t in personal.ledger(flat.carla.user_id) if t.note == "Internet"]


def test_skipping_reserves_nothing(conn, personal, flat):
    row = internet(conn, personal, flat, flat.ben)
    shared_money.skip_household_occurrence(conn, flat.ben, row.id, row.version, flat.clock, skipped=True)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 0
    skipped = internet(conn, personal, flat, flat.ben)
    shared_money.skip_household_occurrence(conn, flat.ben, skipped.id, skipped.version, flat.clock, skipped=False)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1200


def test_ending_a_bill_lets_participants_leave(conn, personal, flat):
    from app.application import households

    series = shared_money.household_bills(conn, personal, flat.ana, flat.household_id, flat.clock).series[0]
    with pytest.raises(PermissionDeniedError):
        shared_money.end_household_bill(conn, flat.ben, series.id, series.version, flat.clock)
    shared_money.end_household_bill(conn, flat.ana, series.id, series.version, flat.clock)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 0  # the 28 Sep bill was due later: removed
    with pytest.raises(ConflictError, match="owe"):
        households.leave(conn, flat.carla, flat.household_id, flat.clock)  # still owes for electricity
    assert balances(conn, household_id=flat.household_id)[flat.carla.user_id] == -4000


def add(conn, personal, flat, *people, anchor=date(2026, 10, 1), method="equal", values=None):
    values = values or [None] * len(people)
    return shared_money.add_household_bill(conn, personal, flat.ana, flat.household_id, shared_money.HouseholdBillInput(
        "Rent", 60000, UTILITIES, Rule("monthly", 1, anchor), method,
        tuple(SplitEntry(p.user_id, v) for p, v in zip(people, values))), flat.clock)


def test_a_bill_due_on_payday_belongs_to_the_next_cycle(conn, personal, flat):
    add(conn, personal, flat, flat.ana, flat.ben)
    assert terms(conn, flat, flat.ana).household_bill_shares_cents == 1200  # only the Internet share


def test_an_exact_template_is_refused_even_when_it_adds_up(conn, personal, flat):
    with pytest.raises(ValidationError) as error:
        add(conn, personal, flat, flat.ana, flat.ben, method="exact", values=[30000, 30000])
    assert "split_method" in error.value.errors


def test_only_participants_change_or_pay_a_bill(conn, personal, flat):
    add(conn, personal, flat, flat.ana, flat.ben, anchor=date(2026, 9, 25))
    rent = next(o for o in shared_money.household_bills(conn, personal, flat.carla, flat.household_id, flat.clock).occurrences
                if o.name == "Rent")
    assert (rent.participant, rent.my_share_cents) == (False, 0)
    for action in (
        lambda: shared_money.pay_household_occurrence(conn, personal, flat.carla, rent.id, rent.version, date(2026, 9, 20),
                                                      flat.clock),
        lambda: shared_money.skip_household_occurrence(conn, flat.carla, rent.id, rent.version, flat.clock,
                                                       skipped=True),
        lambda: shared_money.edit_household_occurrence(conn, flat.carla, rent.id, rent.version, 100, rent.due_date,
                                                       flat.clock),
    ):
        with pytest.raises(PermissionDeniedError):
            action()


def test_shares_are_reported_not_the_cash_fronted(conn, flat):
    """The personal service counts these in budgets and the forecast, instead of the €30 Ana fronted."""
    rows = summary.shares(conn, user_id=flat.ana.user_id, start=date(2026, 9, 1), end_exclusive=date(2026, 10, 1))
    assert sorted((r["category_id"], r["amount_cents"]) for r in rows) == [(1, 1000), (UTILITIES, 3000)]


def test_a_zero_percent_participant_is_explained_not_a_crash(conn, personal, flat):
    """Review finding 3: the schema needs a weight of at least 1, so 0% must be refused with a message."""
    with pytest.raises(ValidationError) as error:
        add(conn, personal, flat, flat.ana, flat.ben, method="percentage", values=[10000, 0])
    assert "split" in error.value.errors and "above zero" in error.value.errors["split"]


def test_nobody_leaves_while_sharing_an_unpaid_bill(conn, personal, clock):
    """Review finding 4: an overdue bill of an ended series must be paid or skipped before a sharer leaves."""
    from app.application import households
    from tests.households.conftest import flat as make_flat

    household, ana, ben, carla = make_flat.__wrapped__(conn, clock, personal)
    everyone = tuple(SplitEntry(a.user_id) for a in (ana, ben, carla))
    series = shared_money.add_household_bill(conn, personal, ana, household.id, shared_money.HouseholdBillInput(
        "Internet", 3600, UTILITIES, Rule("monthly", 1, date(2026, 9, 30)), "equal", everyone), clock)
    clock.advance(days=1)  # 1 October: the 30 September bill is overdue
    shared_money.end_household_bill(conn, ana, series.id, series.version, clock)
    with pytest.raises(ConflictError, match="Internet"):
        households.leave(conn, ben, household.id, clock)
    overdue = next(o for o in shared_money.household_bills(conn, personal, ben, household.id, clock).occurrences
                   if o.status == "overdue")
    shared_money.skip_household_occurrence(conn, ben, overdue.id, overdue.version, clock, skipped=True)
    households.leave(conn, ben, household.id, clock)
