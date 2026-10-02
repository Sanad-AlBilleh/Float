"""What a user actually consumed (SRS §4.7). Pure: callers pass rows from the Ledger and, from day 3,
the user's shares of shared expenses."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

COUNTED_ORIGINS = frozenset({"manual", "bill", "import"})  # "shared" is cash fronted; "settlement" moves debt


class ExpenseLike(Protocol):
    amount_cents: int
    category_id: int | None
    origin: str
    one_off: bool


@dataclass(frozen=True)
class ShareRow:
    """The user's own share of a shared expense."""

    amount_cents: int
    occurred_on: date
    category_id: int
    from_household_bill: bool = False
    one_off: bool = False


def consumption_by_category(expense_rows: Iterable[ExpenseLike], share_rows: Iterable[ShareRow] = ()) -> dict[int, int]:
    totals: dict[int, int] = {}
    for row in expense_rows:
        if row.origin in COUNTED_ORIGINS:
            totals[row.category_id] = totals.get(row.category_id, 0) + row.amount_cents
    for share in share_rows:
        totals[share.category_id] = totals.get(share.category_id, 0) + share.amount_cents
    return totals


def variable_consumption(expense_rows: Iterable[ExpenseLike], share_rows: Iterable[ShareRow] = ()) -> int:
    """Consumption without bills, shares of household bills, or anything marked one-off: the basis of pace."""
    personal = sum(row.amount_cents for row in expense_rows
                   if row.origin in COUNTED_ORIGINS and row.origin != "bill" and not row.one_off)
    shared = sum(share.amount_cents for share in share_rows if not share.from_household_bill and not share.one_off)
    return personal + shared
