"""Ledger service: settings, manual and linked transactions, balance, and queries (FR-05–07, AT-04, AT-05)."""

import sqlite3
from datetime import date

import pytest

from app.ledger.api import (
    TransactionDraft,
    create_linked,
    delete_linked,
    delete_manual,
    get_balance,
    get_expense_rows,
    get_settings,
    get_transaction,
    has_allowance_income,
    list_categories,
    list_transactions,
    update_linked,
    update_manual,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from tests.factories import add_expense, add_income, make_user, start_ledger

START = date(2026, 9, 1)


@pytest.fixture
def ana(conn, clock):
    user = make_user(conn, clock, "ana")
    start_ledger(conn, clock, user, tracking_start=START, opening_cents=10000)
    return user


def balance(conn, clock, user):
    return get_balance(conn, user_id=user.id, as_of=clock.today())


def edit(conn, clock, user, transaction, draft, version=None):
    return update_manual(
        conn, user_id=user.id, transaction_id=transaction.id,
        version=transaction.version if version is None else version,
        draft=draft, today=clock.today(), now=clock.now_utc(),
    )


def link(conn, clock, user, **fields):
    values = {"kind": "expense", "origin": "bill", "amount_cents": 12000, "occurred_on": date(2026, 9, 25),
              "category_id": 4, "income_source": None, "note": "Phone"}
    values.update(fields)
    return create_linked(conn, user_id=user.id, today=clock.today(), now=clock.now_utc(), **values)


def test_settings_are_saved_once(conn, clock, ana):
    assert get_settings(conn, ana.id).opening_balance_cents == 10000
    with pytest.raises(ConflictError):
        start_ledger(conn, clock, ana, tracking_start=START)


def test_tracking_cannot_start_in_the_future(conn, clock):
    ben = make_user(conn, clock, "ben")
    with pytest.raises(ValidationError) as error:
        start_ledger(conn, clock, ben, tracking_start=date(2026, 10, 1))
    assert "tracking_start" in error.value.errors


def test_the_fixed_categories_are_listed_in_order(conn):
    slugs = [category.slug for category in list_categories(conn)]
    assert slugs[0] == "groceries" and slugs[-1] == "other" and len(slugs) == 11


def test_at_04_balance_is_exact_and_follows_edits_and_deletes(conn, clock, ana):
    add_income(conn, clock, ana, 75000, START)
    groceries = add_expense(conn, clock, ana, 2540, date(2026, 9, 20))
    assert balance(conn, clock, ana) == 82460  # €100 + €750 − €25.40
    edited = edit(conn, clock, ana, groceries, TransactionDraft("expense", 3000, date(2026, 9, 20), category_id=1))
    assert balance(conn, clock, ana) == 82000 and edited.version == groceries.version + 1
    delete_manual(conn, user_id=ana.id, transaction_id=edited.id, version=edited.version)
    assert balance(conn, clock, ana) == 85000


def test_a_stale_version_is_a_conflict(conn, clock, ana):
    original = add_expense(conn, clock, ana, 500, START)
    edit(conn, clock, ana, original, TransactionDraft("expense", 600, START, category_id=1))
    with pytest.raises(ConflictError, match="changed"):
        edit(conn, clock, ana, original, TransactionDraft("expense", 700, START, category_id=1))
    with pytest.raises(ConflictError, match="changed"):
        delete_manual(conn, user_id=ana.id, transaction_id=original.id, version=original.version)


def test_other_peoples_transactions_are_not_found(conn, clock, ana):
    ben = make_user(conn, clock, "ben")
    start_ledger(conn, clock, ben, tracking_start=START)
    mine = add_expense(conn, clock, ana, 500, START)
    with pytest.raises(NotFoundError):
        get_transaction(conn, user_id=ben.id, transaction_id=mine.id)
    with pytest.raises(NotFoundError):
        edit(conn, clock, ben, mine, TransactionDraft("expense", 1, START, category_id=1))
    with pytest.raises(NotFoundError):
        delete_manual(conn, user_id=ben.id, transaction_id=mine.id, version=mine.version)


def test_linked_transactions_cannot_be_changed_directly(conn, clock, ana):
    linked = get_transaction(conn, user_id=ana.id, transaction_id=link(conn, clock, ana))
    with pytest.raises(ConflictError, match="managed by"):
        edit(conn, clock, ana, linked, TransactionDraft("expense", 1, START, category_id=1))
    with pytest.raises(ConflictError, match="managed by"):
        delete_manual(conn, user_id=ana.id, transaction_id=linked.id, version=linked.version)


def test_linked_transactions_change_through_their_own_workflow(conn, clock, ana):
    linked_id = link(conn, clock, ana)
    update_linked(conn, user_id=ana.id, transaction_id=linked_id, origin="bill", amount_cents=13000,
                  occurred_on=date(2026, 9, 26), category_id=4, today=clock.today(), now=clock.now_utc())
    changed = get_transaction(conn, user_id=ana.id, transaction_id=linked_id)
    assert (changed.amount_cents, changed.occurred_on, changed.version) == (13000, date(2026, 9, 26), 2)
    with pytest.raises(ConflictError):
        delete_linked(conn, user_id=ana.id, transaction_id=linked_id, origin="shared")
    delete_linked(conn, user_id=ana.id, transaction_id=linked_id, origin="bill")
    with pytest.raises(NotFoundError):
        get_transaction(conn, user_id=ana.id, transaction_id=linked_id)


def test_linked_transactions_respect_the_tracking_period(conn, clock, ana):
    with pytest.raises(ValidationError):
        link(conn, clock, ana, occurred_on=date(2026, 8, 31))
    with pytest.raises(ValidationError):
        link(conn, clock, ana, occurred_on=date(2026, 10, 1))


def test_settlement_transfers_have_no_category(conn, clock, ana):
    paid = link(conn, clock, ana, origin="settlement", category_id=None, amount_cents=1000, note="To Ben")
    received = link(conn, clock, ana, kind="income", origin="settlement", category_id=None,
                    income_source="settlement", amount_cents=500, note="From Carla")
    assert get_transaction(conn, user_id=ana.id, transaction_id=paid).category_id is None
    assert get_transaction(conn, user_id=ana.id, transaction_id=received).income_source == "settlement"
    assert balance(conn, clock, ana) == 10000 - 1000 + 500


def test_an_expense_may_make_the_balance_negative(conn, clock, ana):
    add_expense(conn, clock, ana, 20000, START)
    assert balance(conn, clock, ana) == -10000


def test_transactions_are_listed_newest_first_with_keyset_paging(conn, clock, ana):
    first = add_expense(conn, clock, ana, 100, date(2026, 9, 5))
    second = add_expense(conn, clock, ana, 200, date(2026, 9, 7))
    third = add_expense(conn, clock, ana, 300, date(2026, 9, 7))
    assert [t.id for t in list_transactions(conn, user_id=ana.id)] == [third.id, second.id, first.id]
    page = list_transactions(conn, user_id=ana.id, limit=1, before=(third.occurred_on, third.id))
    assert [t.id for t in page] == [second.id]


def test_only_allowance_income_counts_for_the_reminder(conn, clock, ana):
    add_income(conn, clock, ana, 5000, date(2026, 9, 10), source="other")
    assert not has_allowance_income(conn, user_id=ana.id, start=START, end_inclusive=clock.today())
    add_income(conn, clock, ana, 75000, date(2026, 9, 12))
    assert has_allowance_income(conn, user_id=ana.id, start=START, end_inclusive=clock.today())
    assert not has_allowance_income(conn, user_id=ana.id, start=date(2026, 9, 13), end_inclusive=clock.today())


def test_expense_rows_cover_a_half_open_range(conn, clock, ana):
    add_expense(conn, clock, ana, 100, date(2026, 9, 1), one_off=True)
    add_expense(conn, clock, ana, 200, date(2026, 9, 15))
    add_expense(conn, clock, ana, 300, date(2026, 9, 30))
    add_income(conn, clock, ana, 75000, START)
    rows = get_expense_rows(conn, user_id=ana.id, start=date(2026, 9, 1), end_exclusive=date(2026, 9, 30))
    assert [(row.amount_cents, row.origin, row.one_off) for row in rows] == [(100, "manual", True), (200, "manual", False)]


def test_setup_is_required_before_recording(conn, clock):
    ben = make_user(conn, clock, "ben")
    with pytest.raises(ConflictError, match="setup"):
        add_expense(conn, clock, ben, 100, START)
    with pytest.raises(ConflictError, match="setup"):
        get_balance(conn, user_id=ben.id, as_of=clock.today())


def test_the_schema_rejects_inconsistent_rows(conn, clock, ana):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transactions (user_id, kind, amount_cents, occurred_on, category_id, income_source,"
            " origin, created_at, updated_at) VALUES (?, 'income', 100, '2026-09-30', 1, 'other', 'manual', 'x', 'x')",
            (ana.id,),
        )


def test_settlement_income_only_comes_from_the_settlement_workflow(conn, clock, ana):
    with pytest.raises(sqlite3.IntegrityError, match="settlement"):
        conn.execute(
            "INSERT INTO transactions (user_id, kind, amount_cents, occurred_on, income_source, origin,"
            " created_at, updated_at) VALUES (?, 'income', 100, '2026-09-30', 'settlement', 'manual', 'x', 'x')",
            (ana.id,),
        )
    other = add_income(conn, clock, ana, 100, START, source="other")
    with pytest.raises(sqlite3.IntegrityError, match="settlement"):
        conn.execute("UPDATE transactions SET income_source = 'settlement' WHERE id = ?", (other.id,))


@pytest.mark.parametrize("huge", [2**63, 10**20, -(2**63) - 1])
def test_out_of_range_ids_are_simply_not_found(conn, clock, ana, huge):
    with pytest.raises(NotFoundError):
        get_transaction(conn, user_id=ana.id, transaction_id=huge)
