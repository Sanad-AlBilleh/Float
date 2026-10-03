"""Settlements recorded outside Float and confirmed into both ledgers (FR-24, AT-17)."""

from datetime import date

import pytest

from app.application import shared_money
from app.db.connection import connect
from app.households.api import SplitEntry, balances
from app.ledger.api import list_transactions
from app.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from tests.households.conftest import flat  # noqa: F401 - the shared fixture

DAY = date(2026, 9, 25)


def owe(conn, clock, household, payer, *people, amount=3000):
    entries = tuple(SplitEntry(p.user_id) for p in people)
    shared_money.record_expense(conn, payer, household.id, shared_money.ExpenseDraft(
        amount, date(2026, 9, 19), 1, "Groceries", False, "equal", entries), clock)


def settlement_rows(conn, actor):
    return [t for t in list_transactions(conn, user_id=actor.user_id) if t.origin == "settlement"]


def record(conn, clock, household, initiator, payer, payee, amount=1000, on=DAY):
    return shared_money.record_settlement(conn, initiator, household.id, payer.user_id, payee.user_id, amount, on,
                                          clock)


def test_pending_settlements_change_nothing_until_confirmed(conn, clock, flat):
    household, ana, ben, carla = flat
    owe(conn, clock, household, ben, ana, ben, carla)  # Ana owes Ben €10
    settlement, over = record(conn, clock, household, ana, ana, ben)
    assert settlement.status == "pending" and not over
    assert balances(conn, household_id=household.id)[ana.user_id] == -1000
    with pytest.raises(PermissionDeniedError):
        shared_money.confirm_settlement(conn, ana, settlement.id, settlement.version, clock)  # not the initiator
    shared_money.confirm_settlement(conn, ben, settlement.id, settlement.version, clock)
    assert balances(conn, household_id=household.id)[ana.user_id] == 0
    [paid] = settlement_rows(conn, ana)
    [received] = settlement_rows(conn, ben)
    assert (paid.kind, paid.category_id, paid.amount_cents, paid.occurred_on) == ("expense", None, 1000, DAY)
    assert (received.kind, received.income_source, received.occurred_on) == ("income", "settlement", DAY)
    with pytest.raises(ConflictError):
        shared_money.confirm_settlement(conn, ben, settlement.id, settlement.version, clock)
    with pytest.raises(ConflictError):
        shared_money.cancel_settlement(conn, ana, settlement.id, settlement.version + 1, clock)
    assert len(settlement_rows(conn, ana)) == 1


def test_only_the_counterparty_rejects_and_only_the_initiator_cancels(conn, clock, flat):
    household, ana, ben, carla = flat
    first, _ = record(conn, clock, household, ana, ana, ben)
    with pytest.raises(PermissionDeniedError):
        shared_money.cancel_settlement(conn, ben, first.id, first.version, clock)
    rejected = shared_money.reject_settlement(conn, ben, first.id, first.version, "I never got it", clock)
    assert (rejected.status, rejected.reason) == ("rejected", "I never got it")
    second, _ = record(conn, clock, household, ben, ana, ben)  # the payee may record it too
    with pytest.raises(PermissionDeniedError):
        shared_money.reject_settlement(conn, ben, second.id, second.version, "", clock)
    assert shared_money.cancel_settlement(conn, ben, second.id, second.version, clock).status == "cancelled"
    assert settlement_rows(conn, ana) == settlement_rows(conn, ben) == []
    with pytest.raises(PermissionDeniedError):
        record(conn, clock, household, carla, ana, ben)  # a bystander cannot record someone else's transfer


def test_more_than_suggested_is_allowed_with_a_warning(conn, clock, flat):
    household, ana, ben, carla = flat
    owe(conn, clock, household, ben, ana, ben, carla)
    _, over = record(conn, clock, household, ana, ana, ben, amount=1001)
    assert over


def test_bad_settlements_are_refused(conn, clock, flat):
    household, ana, ben, carla = flat
    for kwargs, field in (({"on": date(2026, 8, 31)}, "paid_on"), ({"on": date(2026, 10, 1)}, "paid_on"),
                          ({"amount": 0}, "amount")):
        with pytest.raises(ValidationError) as error:
            record(conn, clock, household, ana, ana, ben, **kwargs)
        assert field in error.value.errors
    with pytest.raises(ValidationError):
        record(conn, clock, household, ana, ana, ana)


def test_a_reason_is_at_most_200_characters(conn, clock, flat):
    household, ana, ben, carla = flat
    settlement, _ = record(conn, clock, household, ana, ana, ben)
    with pytest.raises(ValidationError):
        shared_money.reject_settlement(conn, ben, settlement.id, settlement.version, "x" * 201, clock)


def test_a_confirm_and_a_cancel_race_has_one_winner(conn, clock, flat, tmp_path):
    household, ana, ben, carla = flat
    settlement, _ = record(conn, clock, household, ana, ana, ben)
    other = connect(tmp_path / "test.sqlite3")
    try:
        shared_money.confirm_settlement(conn, ben, settlement.id, settlement.version, clock)
        with pytest.raises(ConflictError):
            shared_money.cancel_settlement(other, ana, settlement.id, settlement.version, clock)
    finally:
        other.close()
    assert len(settlement_rows(conn, ana)) == len(settlement_rows(conn, ben)) == 1
