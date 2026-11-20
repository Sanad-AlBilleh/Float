"""Shared expenses across Households and the payer's ledger in the personal service (FR-20–22, AT-14, AT-15)."""

from datetime import date

import pytest

from app.application import shared_money
from app.households.api import SplitEntry
from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from tests.households.conftest import flat  # noqa: F401 - the shared fixture

GROCERIES = 1


def draft(*people, amount=3000, method="equal", values=None, on=date(2026, 9, 19), description="Groceries"):
    values = values or [None] * len(people)
    return shared_money.ExpenseDraft(amount, on, GROCERIES, description, False, method,
                                     tuple(SplitEntry(p.user_id, v) for p, v in zip(people, values)))


def shared_rows(conn, personal, actor):
    return [t for t in personal.ledger(actor.user_id) if t.origin == "shared"]


def test_recording_writes_the_split_and_the_payers_full_expense(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    assert expense.shares == {ana.user_id: 1000, ben.user_id: 1000, carla.user_id: 1000}
    [linked] = shared_rows(conn, personal, ana)
    assert (linked.id, linked.amount_cents, linked.category_id) == (expense.payer_transaction_id, 3000, GROCERIES)
    assert shared_rows(conn, personal, ben) == []  # only the payer's cash moved
    events = conn.execute("SELECT household_id FROM audit_events WHERE entity_type = 'shared_expense'").fetchall()
    assert [row[0] for row in events] == [household.id]


def test_the_payer_may_leave_themselves_out(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ben, carla, amount=1001), clock)
    assert expense.shares == {ben.user_id: 501, carla.user_id: 500}


def test_only_the_payer_edits_or_deletes(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    with pytest.raises(PermissionDeniedError):
        shared_money.edit_expense(conn, personal, ben, expense.id, expense.version, draft(ana, ben), clock)
    with pytest.raises(PermissionDeniedError):
        shared_money.delete_expense(conn, personal, ben, expense.id, expense.version, clock)


def test_an_edit_changes_the_linked_expense_in_the_same_transaction(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    edited = shared_money.edit_expense(conn, personal, ana, expense.id, expense.version,
                                       draft(ana, ben, amount=4000, on=date(2026, 9, 20)), clock)
    assert edited.shares == {ana.user_id: 2000, ben.user_id: 2000} and edited.version == expense.version + 1
    [linked] = shared_rows(conn, personal, ana)
    assert (linked.amount_cents, linked.occurred_on) == (4000, date(2026, 9, 20))
    with pytest.raises(ConflictError):
        shared_money.edit_expense(conn, personal, ana, expense.id, expense.version, draft(ana, ben), clock)
    shared_money.delete_expense(conn, personal, ana, edited.id, edited.version, clock)
    assert shared_rows(conn, personal, ana) == []


def test_participants_must_be_active_members(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    from tests.factories import make_member

    stranger = make_member(personal, 9, "Eve")
    with pytest.raises(ValidationError) as error:
        shared_money.record_expense(conn, personal, ana, household.id, draft(ana, stranger), clock)
    assert "participants" in error.value.errors
    with pytest.raises(NotFoundError):
        shared_money.record_expense(conn, personal, stranger, household.id, draft(stranger), clock)


def test_the_date_must_be_inside_the_payers_tracking(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    for day in (date(2026, 8, 31), date(2026, 10, 1)):
        with pytest.raises(ValidationError) as error:
            shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, on=day), clock)
        assert "spent_on" in error.value.errors
    assert shared_rows(conn, personal, ana) == []


def test_every_field_is_checked(conn, personal, clock, flat):
    household, ana, ben, carla = flat
    bad = shared_money.ExpenseDraft(0, date(2026, 9, 19), 99, "", False, "exact",
                                    (SplitEntry(ana.user_id, 1),))
    with pytest.raises(ValidationError) as error:
        shared_money.record_expense(conn, personal, ana, household.id, bad, clock)
    assert {"amount", "category_id", "description"} <= set(error.value.errors)


def test_archiving_needs_everyone_settled(conn, personal, clock, flat):
    from app.application import households

    household, ana, ben, carla = flat
    shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    with pytest.raises(ConflictError, match="settled"):
        households.archive(conn, ana, household.id, household.version, clock)
    with pytest.raises(ConflictError, match="owe"):
        households.leave(conn, ben, household.id, clock)


def test_an_expense_shared_with_someone_who_left_can_no_longer_change(conn, personal, clock, flat):
    """Review finding 1: changing it would move a former member's balance, which nobody could then settle."""
    from app.application import households

    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    settlement, _ = shared_money.record_settlement(conn, personal, ben, household.id, ben.user_id, ana.user_id, 1000,
                                                   date(2026, 9, 30), clock)
    shared_money.confirm_settlement(conn, personal, ana, settlement.id, settlement.version, clock)
    households.leave(conn, ben, household.id, clock)
    before = balances(conn, household.id)
    with pytest.raises(ConflictError, match="left"):
        shared_money.delete_expense(conn, personal, ana, expense.id, expense.version, clock)
    with pytest.raises(ConflictError, match="left"):
        shared_money.edit_expense(conn, personal, ana, expense.id, expense.version, draft(ana, carla), clock)
    assert balances(conn, household.id) == before
    assert len(shared_rows(conn, personal, ana)) == 1


def balances(conn, household_id):
    from app.households.api import balances as nets

    return nets(conn, household_id=household_id)


def test_nothing_is_saved_when_the_ledger_is_down(conn, personal, clock, flat):
    """The designed partial failure (§3): a clear error and no half-recorded money."""
    from app.clients.personal import PersonalUnavailable

    household, ana, ben, carla = flat
    personal.down = True
    with pytest.raises(PersonalUnavailable, match="nothing was saved"):
        shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben), clock)
    personal.down = False
    assert shared_money.list_expenses(conn, ana, household.id) == [] and shared_rows(conn, personal, ana) == []


def test_a_failed_household_write_undoes_the_ledger_row(conn, personal, clock, flat, monkeypatch):
    """Compensation (ADR-7): the ledger row is created first, so it is deleted again if this service fails."""
    from app.households import api as households_api

    household, ana, ben, carla = flat

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(households_api, "create_expense", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben), clock)
    assert shared_rows(conn, personal, ana) == [] and personal.creates == 1


def test_a_failed_commit_also_undoes_the_ledger_row(conn, personal, clock, flat, monkeypatch):
    """The COMMIT itself can fail (a deadlock, a dropped connection); the ledger row is undone then too."""
    from contextlib import contextmanager

    household, ana, ben, carla = flat

    @contextmanager
    def commit_fails(connection):
        connection.execute("BEGIN TRANSACTION")
        yield connection
        connection.execute("ROLLBACK TRANSACTION")
        raise RuntimeError("connection lost during COMMIT")
    monkeypatch.setattr(shared_money, "transaction", commit_fails)
    with pytest.raises(RuntimeError, match="during COMMIT"):
        shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben), clock)
    assert shared_rows(conn, personal, ana) == [] and personal.creates == 1
    assert conn.execute("SELECT COUNT(*) FROM shared_expenses").fetchone()[0] == 0


def test_an_edit_the_ledger_refuses_changes_nothing_here(conn, personal, clock, flat):
    """The ledger is called last, so its refusal rolls this service's change back."""
    household, ana, ben, carla = flat
    expense = shared_money.record_expense(conn, personal, ana, household.id, draft(ana, ben, carla), clock)
    personal.down = True
    with pytest.raises(Exception, match="nothing was saved"):
        shared_money.edit_expense(conn, personal, ana, expense.id, expense.version, draft(ana, ben, amount=9000),
                                  clock)
    personal.down = False
    assert shared_money.get_expense(conn, ana, household.id, expense.id) == expense
