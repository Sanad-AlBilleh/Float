"""Bill workflows across Planning and the Ledger, each in one transaction (FR-12–13, AT-08, AT-09, AT-20)."""

from datetime import date, datetime

import pytest

from app.application import bills
from app.application.context import Actor
from app.ledger.api import get_balance, list_transactions
from app.planning import api as planning
from app.shared.clock import FixedClock
from app.shared.errors import ConflictError, ValidationError
from app.shared.recurrence import Rule
from tests.conftest import MADRID
from tests.factories import complete_setup, make_user

JULY = date(2026, 7, 1)


@pytest.fixture
def today():
    return FixedClock(datetime(2026, 9, 20, 10, tzinfo=MADRID), MADRID)


@pytest.fixture
def ana(conn, today):
    user = make_user(conn, today)
    complete_setup(conn, today, user, tracking_start=JULY, opening_cents=50000)
    return Actor(user.id)


def add(conn, actor, clock, *, name="Gym", amount=4000, anchor=date(2026, 7, 5), category_id=6, **rule):
    return bills.add_series(conn, actor, bills.SeriesInput(name, amount, category_id,
                                                           Rule(rule.pop("freq", "monthly"), 1, anchor, **rule)),
                            clock)


def view(conn, actor, clock):
    return {o.scheduled_date: o for o in bills.overview(conn, actor, clock).occurrences}


def occurrence_on(conn, actor, clock, day):
    return view(conn, actor, clock)[day]


def pay(conn, actor, clock, day, paid_on=None):
    occurrence = occurrence_on(conn, actor, clock, day)
    return bills.pay_occurrence(conn, actor, occurrence.id, occurrence.version, paid_on or day, clock)


def bill_expenses(conn, actor):
    return [t for t in list_transactions(conn, user_id=actor.user_id) if t.origin == "bill"]


def reserved(conn, actor, clock):
    return bills.overview(conn, actor, clock).reserved_cents


def test_overview_materializes_and_labels_each_occurrence(conn, ana, today):
    add(conn, ana, today)
    rows = bills.overview(conn, ana, today).occurrences
    assert [(o.scheduled_date, o.status) for o in rows] == [
        (date(2026, 7, 5), "overdue"), (date(2026, 8, 5), "overdue"), (date(2026, 9, 5), "overdue"),
        (date(2026, 10, 5), "upcoming"),
    ]


def test_paying_creates_exactly_one_linked_expense(conn, ana, today):
    add(conn, ana, today)
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 5))
    transaction_id = bills.pay_occurrence(conn, ana, occurrence.id, occurrence.version, today.today(), today)
    [expense] = bill_expenses(conn, ana)
    assert (expense.id, expense.amount_cents, expense.category_id, expense.occurred_on) == (
        transaction_id, 4000, 6, date(2026, 9, 20))
    with pytest.raises(ConflictError):
        bills.pay_occurrence(conn, ana, occurrence.id, occurrence.version, today.today(), today)
    with pytest.raises(ConflictError):
        bills.pay_occurrence(conn, ana, occurrence.id, occurrence.version + 1, today.today(), today)
    assert len(bill_expenses(conn, ana)) == 1
    assert occurrence_on(conn, ana, today, date(2026, 9, 5)).status == "paid"


def test_a_payment_date_must_be_inside_tracking(conn, ana, today):
    add(conn, ana, today)
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 5))
    for day in (date(2026, 6, 30), date(2026, 9, 21)):
        with pytest.raises(ValidationError) as error:
            bills.pay_occurrence(conn, ana, occurrence.id, occurrence.version, day, today)
        assert "paid_on" in error.value.errors
    assert bill_expenses(conn, ana) == []


def test_a_failure_after_the_ledger_insert_rolls_everything_back(conn, ana, today, monkeypatch):
    add(conn, ana, today)
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 5))

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(planning, "link_payment", broken)
    with pytest.raises(RuntimeError):
        bills.pay_occurrence(conn, ana, occurrence.id, occurrence.version, today.today(), today)
    assert bill_expenses(conn, ana) == []
    assert conn.execute("SELECT COUNT(*) FROM audit_events WHERE entity_type = 'bill_occurrence'").fetchone()[0] == 0


def test_undo_removes_the_expense_and_the_link_together(conn, ana, today):
    add(conn, ana, today)
    pay(conn, ana, today, date(2026, 9, 5))
    paid = occurrence_on(conn, ana, today, date(2026, 9, 5))
    with pytest.raises(ConflictError, match="Undo"):
        bills.edit_occurrence(conn, ana, paid.id, paid.version, 5000, paid.due_date, today)
    with pytest.raises(ConflictError, match="Undo"):
        bills.skip_occurrence(conn, ana, paid.id, paid.version, today)
    bills.undo_payment(conn, ana, paid.id, paid.version, today)
    assert bill_expenses(conn, ana) == []
    assert occurrence_on(conn, ana, today, date(2026, 9, 5)).status == "overdue"
    with pytest.raises(ConflictError):
        bills.undo_payment(conn, ana, paid.id, paid.version + 1, today)


def test_skipped_occurrences_reserve_nothing_until_unskipped(conn, ana, today):
    add(conn, ana, today, anchor=date(2026, 9, 25))
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 25))
    assert reserved(conn, ana, today) == 4000
    bills.skip_occurrence(conn, ana, occurrence.id, occurrence.version, today)
    skipped = occurrence_on(conn, ana, today, date(2026, 9, 25))
    assert skipped.status == "skipped" and reserved(conn, ana, today) == 0
    with pytest.raises(ConflictError, match="skipped"):
        bills.pay_occurrence(conn, ana, skipped.id, skipped.version, today.today(), today)
    bills.unskip_occurrence(conn, ana, skipped.id, skipped.version, today)
    assert occurrence_on(conn, ana, today, date(2026, 9, 25)).status == "reserved"


def test_fixture_e_split_keeps_paid_history_and_the_overdue_occurrence(conn, ana, today):
    add(conn, ana, today)
    pay(conn, ana, today, date(2026, 7, 5))
    pay(conn, ana, today, date(2026, 8, 5))
    august = occurrence_on(conn, ana, today, date(2026, 8, 5))
    with pytest.raises(ConflictError, match="paid"):
        bills.split_series(conn, ana, august.id, august.version,
                           bills.SeriesInput("Gym", 4500, 6, Rule("monthly", 1, date(2026, 8, 5))), today)
    october = occurrence_on(conn, ana, today, date(2026, 10, 5))
    new = bills.split_series(conn, ana, october.id, october.version,
                             bills.SeriesInput("Gym", 4500, 6, Rule("monthly", 1, date(2026, 10, 5))), today)
    rows = view(conn, ana, today)
    old = planning.get_series(conn, user_id=ana.user_id, series_id=rows[date(2026, 9, 5)].series_id)
    assert old.rule.until == date(2026, 10, 4)
    assert (rows[date(2026, 9, 5)].amount_cents, rows[date(2026, 9, 5)].status) == (4000, "overdue")
    assert (rows[date(2026, 10, 5)].series_id, rows[date(2026, 10, 5)].amount_cents) == (new.id, 4500)
    assert new.rule.anchor == date(2026, 10, 5)
    assert [rows[day].status for day in (date(2026, 7, 5), date(2026, 8, 5))] == ["paid", "paid"]
    assert len(bill_expenses(conn, ana)) == 2


def test_a_split_keeps_the_remaining_count(conn, ana, today):
    add(conn, ana, today, count=6)
    october = occurrence_on(conn, ana, today, date(2026, 10, 5))
    new = bills.split_series(conn, ana, october.id, october.version,
                             bills.SeriesInput("Gym", 4500, 6, Rule("monthly", 1, date(2026, 10, 5))), today)
    assert new.rule.count == 3


def test_splitting_at_the_first_occurrence_rewrites_the_series(conn, ana, today):
    series = add(conn, ana, today, anchor=date(2026, 9, 25))
    first = occurrence_on(conn, ana, today, date(2026, 9, 25))
    changed = bills.split_series(conn, ana, first.id, first.version,
                                 bills.SeriesInput("Phone", 1500, 4, Rule("monthly", 1, date(2026, 9, 27))), today)
    assert changed.id == series.id and changed.name == "Phone"
    rows = view(conn, ana, today)
    assert sorted(rows) == [date(2026, 9, 27), date(2026, 10, 27)]
    assert {o.amount_cents for o in rows.values()} == {1500}


def test_a_split_cannot_start_before_its_occurrence(conn, ana, today):
    add(conn, ana, today)
    october = occurrence_on(conn, ana, today, date(2026, 10, 5))
    with pytest.raises(ValidationError) as error:
        bills.split_series(conn, ana, october.id, october.version,
                           bills.SeriesInput("Gym", 4500, 6, Rule("monthly", 1, date(2026, 9, 30))), today)
    assert "anchor_date" in error.value.errors


def test_moving_a_due_date_never_regenerates_the_original(conn, ana, today):
    add(conn, ana, today, anchor=date(2026, 9, 25))
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 25))
    bills.edit_occurrence(conn, ana, occurrence.id, occurrence.version, 4200, date(2026, 10, 2), today)
    conn.execute("UPDATE bill_series SET materialized_through = NULL")
    rows = bills.overview(conn, ana, today).occurrences
    assert [(o.scheduled_date, o.due_date, o.amount_cents, o.status) for o in rows] == [
        (date(2026, 9, 25), date(2026, 10, 2), 4200, "upcoming"),
        (date(2026, 10, 25), date(2026, 10, 25), 4000, "upcoming"),
    ]


def test_ending_a_series_keeps_overdue_occurrences(conn, ana, today):
    series = add(conn, ana, today, anchor=date(2026, 9, 5))
    occurrence_on(conn, ana, today, date(2026, 9, 5))
    bills.end_series(conn, ana, series.id, series.version, today)
    rows = view(conn, ana, today)
    assert list(rows) == [date(2026, 9, 5)] and rows[date(2026, 9, 5)].status == "overdue"
    assert planning.get_series(conn, user_id=ana.user_id, series_id=series.id).ended
    with pytest.raises(ConflictError):
        bills.end_series(conn, ana, series.id, series.version, today)


def test_paying_a_bill_moves_cash_and_reservation_by_the_same_amount(conn, ana, today):
    add(conn, ana, today, anchor=date(2026, 9, 25), amount=12000)
    cash_before, reserved_before = get_balance(conn, user_id=ana.user_id, as_of=today.today()), reserved(conn, ana, today)
    pay(conn, ana, today, date(2026, 9, 25), paid_on=today.today())
    cash_after, reserved_after = get_balance(conn, user_id=ana.user_id, as_of=today.today()), reserved(conn, ana, today)
    assert cash_before - cash_after == reserved_before - reserved_after == 12000


def test_every_bill_change_is_audited(conn, ana, today):
    series = add(conn, ana, today, anchor=date(2026, 9, 25))
    pay(conn, ana, today, date(2026, 9, 25), paid_on=today.today())
    paid = occurrence_on(conn, ana, today, date(2026, 9, 25))
    bills.undo_payment(conn, ana, paid.id, paid.version, today)
    bills.end_series(conn, ana, series.id, series.version, today)
    actions = [tuple(row) for row in conn.execute(
        "SELECT entity_type, action FROM audit_events WHERE entity_type LIKE 'bill%' ORDER BY id")]
    assert actions == [("bill_series", "create"), ("bill_occurrence", "pay"), ("bill_occurrence", "undo_payment"),
                       ("bill_series", "end")]


def test_stale_changes_are_conflicts(conn, ana, today):
    add(conn, ana, today, anchor=date(2026, 9, 25))
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 25))
    bills.edit_occurrence(conn, ana, occurrence.id, occurrence.version, 4100, occurrence.due_date, today)
    for change in (
        lambda: bills.edit_occurrence(conn, ana, occurrence.id, occurrence.version, 4200, occurrence.due_date, today),
        lambda: bills.skip_occurrence(conn, ana, occurrence.id, occurrence.version, today),
    ):
        with pytest.raises(ConflictError, match="changed"):
            change()
    assert occurrence_on(conn, ana, today, date(2026, 9, 25)).amount_cents == 4100


def test_an_occurrence_cannot_move_before_tracking(conn, ana, today):
    add(conn, ana, today, anchor=date(2026, 9, 25))
    occurrence = occurrence_on(conn, ana, today, date(2026, 9, 25))
    with pytest.raises(ValidationError) as error:
        bills.edit_occurrence(conn, ana, occurrence.id, occurrence.version, 0, date(2026, 6, 30), today)
    assert set(error.value.errors) == {"amount", "due_date"}


def test_ending_removes_a_bill_due_today_but_keeps_skipped_ones(conn, ana, today):
    series = add(conn, ana, today, anchor=date(2026, 9, 20), freq="weekly")
    rows = view(conn, ana, today)
    later = rows[date(2026, 9, 27)]
    bills.skip_occurrence(conn, ana, later.id, later.version, today)
    bills.end_series(conn, ana, series.id, series.version, today)
    assert [(day, o.status) for day, o in view(conn, ana, today).items()] == [(date(2026, 9, 27), "skipped")]
