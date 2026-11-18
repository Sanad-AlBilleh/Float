"""Pure planning rules: occurrence status (FR-11, AT-08)."""

from datetime import date

import pytest

from app.planning.api import Occurrence, occurrence_status

TODAY = date(2026, 9, 20)
NEXT_ALLOWANCE = date(2026, 10, 1)


def occurrence(due: date, *, skipped: bool = False, paid: int | None = None) -> Occurrence:
    return Occurrence(id=1, series_id=1, name="Phone", category_id=4, scheduled_date=due, due_date=due,
                      amount_cents=12000, skipped=skipped, paid_transaction_id=paid, version=1)


@pytest.mark.parametrize(
    "due, skipped, paid, expected",
    [
        (date(2026, 9, 25), False, None, "reserved"),
        (date(2026, 9, 20), False, None, "reserved"),  # due today is not yet overdue
        (date(2026, 9, 15), False, None, "overdue"),
        (date(2026, 10, 1), False, None, "upcoming"),  # due on the next allowance date: next cycle (AT-08)
        (date(2026, 10, 20), False, None, "upcoming"),
        (date(2026, 9, 15), False, 7, "paid"),
        (date(2026, 9, 15), True, None, "skipped"),
    ],
)
def test_occurrence_status(due, skipped, paid, expected):
    assert occurrence_status(occurrence(due, skipped=skipped, paid=paid), today=TODAY,
                             next_allowance=NEXT_ALLOWANCE) == expected
