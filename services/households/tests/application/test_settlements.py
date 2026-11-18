"""Settlements recorded outside Float and confirmed into both ledgers in the personal service (FR-24, AT-17)."""

from datetime import date

import pytest

from app.application import shared_money
from app.db.connection import connect
from app.households.api import SplitEntry, balances
from app.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from tests.households.conftest import flat  # noqa: F401 - the shared fixture

DAY = date(2026, 9, 25)


def owe(conn, personal, clock, household, payer, *people, amount=3000):
    entries = tuple(SplitEntry(p.user_id) for p in people)
    shared_money.record_expense(conn, personal, payer, household.id, shared_money.ExpenseDraft(
        amount, date(2026, 9, 19), 1, "Groceries", False, "equal", entries), clock)


def settlement_rows(conn, personal, actor):
    return [t for t in personal.ledger(actor.user_id) if t.origin == "settlement"]


def record(conn, personal, clock, household, initiator, payer, payee, amount=1000, on=DAY):
    return shared_money.record_settlement(conn, personal, initiator, household.id, payer.user_id, payee.user_id, amount, on,
                                          clock)


def test_pending_settlements_change_nothing_until_confirmed(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    owe(conn, personal, clock, household, ben, ana, ben, carla)  # Ana owes Ben €10
    settlement, over = record(conn, personal, clock, household, ana, ana, ben)
    assert settlement.status == "pending" and not over
    assert balances(conn, household_id=household.id)[ana.user_id] == -1000
    with pytest.raises(PermissionDeniedError):
        shared_money.confirm_settlement(conn, personal, ana, settlement.id, settlement.version, clock)  # not the initiator
    shared_money.confirm_settlement(conn, personal, ben, settlement.id, settlement.version, clock)
    assert balances(conn, household_id=household.id)[ana.user_id] == 0
    [paid] = settlement_rows(conn, personal, ana)
    [received] = settlement_rows(conn, personal, ben)
    assert (paid.kind, paid.category_id, paid.amount_cents, paid.occurred_on) == ("expense", None, 1000, DAY)
    assert (received.kind, received.income_source, received.occurred_on) == ("income", "settlement", DAY)
    with pytest.raises(ConflictError):
        shared_money.confirm_settlement(conn, personal, ben, settlement.id, settlement.version, clock)
    with pytest.raises(ConflictError):
        shared_money.cancel_settlement(conn, ana, settlement.id, settlement.version + 1, clock)
    assert len(settlement_rows(conn, personal, ana)) == 1


def test_only_the_counterparty_rejects_and_only_the_initiator_cancels(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    first, _ = record(conn, personal, clock, household, ana, ana, ben)
    with pytest.raises(PermissionDeniedError):
        shared_money.cancel_settlement(conn, ben, first.id, first.version, clock)
    rejected = shared_money.reject_settlement(conn, ben, first.id, first.version, "I never got it", clock)
    assert (rejected.status, rejected.reason) == ("rejected", "I never got it")
    second, _ = record(conn, personal, clock, household, ben, ana, ben)  # the payee may record it too
    with pytest.raises(PermissionDeniedError):
        shared_money.reject_settlement(conn, ben, second.id, second.version, "", clock)
    assert shared_money.cancel_settlement(conn, ben, second.id, second.version, clock).status == "cancelled"
    assert settlement_rows(conn, personal, ana) == settlement_rows(conn, personal, ben) == []
    with pytest.raises(PermissionDeniedError):
        record(conn, personal, clock, household, carla, ana, ben)  # a bystander cannot record someone else's transfer


def test_more_than_suggested_is_allowed_with_a_warning(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    owe(conn, personal, clock, household, ben, ana, ben, carla)
    _, over = record(conn, personal, clock, household, ana, ana, ben, amount=1001)
    assert over


def test_bad_settlements_are_refused(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    for kwargs, field in (({"on": date(2026, 8, 31)}, "paid_on"), ({"on": date(2026, 10, 1)}, "paid_on"),
                          ({"amount": 0}, "amount")):
        with pytest.raises(ValidationError) as error:
            record(conn, personal, clock, household, ana, ana, ben, **kwargs)
        assert field in error.value.errors
    with pytest.raises(ValidationError):
        record(conn, personal, clock, household, ana, ana, ana)


def test_a_reason_is_at_most_200_characters(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    settlement, _ = record(conn, personal, clock, household, ana, ana, ben)
    with pytest.raises(ValidationError):
        shared_money.reject_settlement(conn, ben, settlement.id, settlement.version, "x" * 201, clock)


def test_a_confirm_and_a_cancel_race_has_one_winner(conn, personal, clock, flat, database_url):
    household, ana, ben, carla = flat
    settlement, _ = record(conn, personal, clock, household, ana, ana, ben)
    other = connect(database_url, retries=0)
    try:
        shared_money.confirm_settlement(conn, personal, ben, settlement.id, settlement.version, clock)
        with pytest.raises(ConflictError):
            shared_money.cancel_settlement(other, ana, settlement.id, settlement.version, clock)
    finally:
        other.close()
    assert len(settlement_rows(conn, personal, ana)) == len(settlement_rows(conn, personal, ben)) == 1


def test_a_failed_second_ledger_row_undoes_the_first(conn, personal, clock, flat):
    """Compensation (ADR-7): if the payee's income cannot be recorded, the payer's expense is deleted again."""
    from app.clients.personal import PersonalUnavailable

    household, ana, ben, carla = flat
    settlement, _ = record(conn, personal, clock, household, ana, ana, ben)
    personal.fail_after_creates = personal.creates + 2  # the second create of this confirm fails
    with pytest.raises(PersonalUnavailable):
        shared_money.confirm_settlement(conn, personal, ben, settlement.id, settlement.version, clock)
    assert settlement_rows(conn, personal, ana) == [] and settlement_rows(conn, personal, ben) == []
    assert shared_money.households.get_settlement(conn, settlement_id=settlement.id).status == "pending"
