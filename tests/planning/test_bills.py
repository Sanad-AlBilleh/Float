"""Bill series and idempotent materialization (FR-09–11, AT-07, AT-08)."""

from datetime import date

import pytest

from app.db.connection import connect
from app.planning.api import (
    create_series,
    ensure_materialized,
    get_obligations,
    get_occurrence,
    get_series,
    list_occurrences,
)
from app.shared.dates import cycle_for
from app.shared.errors import NotFoundError, ValidationError
from app.shared.recurrence import Rule
from tests.factories import complete_setup, make_user

START = date(2026, 9, 1)
CATEGORIES = set(range(1, 12))
HORIZON = date(2026, 11, 1)


@pytest.fixture
def ana(conn, clock):
    user = make_user(conn, clock)
    complete_setup(conn, clock, user, tracking_start=START)
    return user


def phone(conn, clock, user, *, anchor=date(2026, 9, 25), amount=12000, **rule):
    return create_series(conn, user_id=user.id, name="Phone + gym", amount_cents=amount, category_id=4,
                         rule=Rule("monthly", 1, anchor, **rule), tracking_start=START, category_ids=CATEGORIES,
                         now=clock.now_utc())


def dates(conn, user, start=START, end=date(2027, 1, 1)):
    return [o.scheduled_date for o in list_occurrences(conn, user_id=user.id, start=start, end_exclusive=end)]


def test_a_series_cannot_start_before_tracking(conn, clock, ana):
    with pytest.raises(ValidationError) as error:
        phone(conn, clock, ana, anchor=date(2026, 8, 31))
    assert "anchor_date" in error.value.errors


def test_a_series_reports_every_invalid_field(conn, clock, ana):
    with pytest.raises(ValidationError) as error:
        create_series(conn, user_id=ana.id, name="", amount_cents=0, category_id=99,
                      rule=Rule("monthly", 1, START), tracking_start=START, category_ids=CATEGORIES,
                      now=clock.now_utc())
    assert set(error.value.errors) == {"name", "amount", "category_id"}


def test_materialization_fills_the_horizon_once(conn, clock, ana):
    series = phone(conn, clock, ana)
    assert ensure_materialized(conn, user_id=ana.id, horizon_end=HORIZON) == 2
    assert dates(conn, ana) == [date(2026, 9, 25), date(2026, 10, 25)]
    assert ensure_materialized(conn, user_id=ana.id, horizon_end=HORIZON) == 0
    assert get_series(conn, user_id=ana.id, series_id=series.id).materialized_through == date(2026, 10, 31)
    assert ensure_materialized(conn, user_id=ana.id, horizon_end=date(2026, 12, 1)) == 1
    assert dates(conn, ana)[-1] == date(2026, 11, 25)


def test_two_connections_materializing_the_same_horizon_create_no_duplicates(conn, clock, ana, tmp_path):
    phone(conn, clock, ana)
    other = connect(tmp_path / "test.sqlite3")
    try:
        conn.execute("UPDATE bill_series SET materialized_through = NULL")  # as if a restart lost the watermark
        assert ensure_materialized(conn, user_id=ana.id, horizon_end=HORIZON) == 2
        other.execute("UPDATE bill_series SET materialized_through = NULL")
        assert ensure_materialized(other, user_id=ana.id, horizon_end=HORIZON) == 0
    finally:
        other.close()
    assert dates(conn, ana) == [date(2026, 9, 25), date(2026, 10, 25)]


def test_count_limited_series_stop(conn, clock, ana):
    phone(conn, clock, ana, anchor=date(2026, 9, 5), count=2)
    ensure_materialized(conn, user_id=ana.id, horizon_end=date(2027, 3, 1))
    assert dates(conn, ana) == [date(2026, 9, 5), date(2026, 10, 5)]


def test_obligations_reserve_bills_due_before_the_next_allowance(conn, clock, ana):
    phone(conn, clock, ana)
    create_series(conn, user_id=ana.id, name="Rent", amount_cents=30000, category_id=3,
                  rule=Rule("once", 1, date(2026, 10, 1)), tracking_start=START, category_ids=CATEGORIES,
                  now=clock.now_utc())
    ensure_materialized(conn, user_id=ana.id, horizon_end=HORIZON)
    obligations = get_obligations(conn, user_id=ana.id, cycle=cycle_for(date(2026, 9, 20), 1))
    assert obligations.personal_bills_cents == 12000  # 25 Sep only; 1 Oct belongs to the next cycle
    assert [o.due_date for o in obligations.occurrences] == [date(2026, 9, 25)]


def test_other_peoples_occurrences_are_not_found(conn, clock, ana):
    phone(conn, clock, ana)
    ensure_materialized(conn, user_id=ana.id, horizon_end=HORIZON)
    ben = make_user(conn, clock, "ben")
    occurrence_id = list_occurrences(conn, user_id=ana.id, start=START, end_exclusive=HORIZON)[0].id
    with pytest.raises(NotFoundError):
        get_occurrence(conn, user_id=ben.id, occurrence_id=occurrence_id)
    with pytest.raises(NotFoundError):
        get_occurrence(conn, user_id=ana.id, occurrence_id=2**63)
