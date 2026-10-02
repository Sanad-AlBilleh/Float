"""Consumption and variable consumption (SRS §4.7, AT-12's shared-expense rule)."""

from datetime import date

from app.insights.api import ShareRow, consumption_by_category, variable_consumption
from app.ledger.api import ExpenseRow

DAY = date(2026, 9, 19)
GROCERIES, EATING_OUT, UTILITIES = 1, 2, 5


def row(cents, category=GROCERIES, origin="manual", one_off=False, number=1):
    return ExpenseRow(number, cents, DAY, category, origin, one_off)


def test_a_shared_expense_counts_only_the_users_share():
    rows = [row(3000, origin="shared")]  # Ana fronted the flat's €30 groceries
    shares = [ShareRow(1000, DAY, GROCERIES)]
    assert consumption_by_category(rows, shares) == {GROCERIES: 1000}


def test_settlements_count_nothing():
    assert consumption_by_category([row(4000, category=None, origin="settlement")], []) == {}


def test_manual_bill_and_import_expenses_count():
    rows = [row(100), row(200, EATING_OUT, "bill"), row(300, origin="import"), row(400, one_off=True)]
    assert consumption_by_category(rows, []) == {GROCERIES: 800, EATING_OUT: 200}


def test_variable_consumption_leaves_out_bills_household_bills_and_one_offs():
    rows = [row(18800), row(3200, one_off=True), row(12000, UTILITIES, "bill"), row(3000, origin="shared")]
    shares = [ShareRow(1000, DAY, GROCERIES), ShareRow(3000, DAY, UTILITIES),
              ShareRow(1200, DAY, UTILITIES, from_household_bill=True), ShareRow(500, DAY, GROCERIES, one_off=True)]
    assert variable_consumption(rows, shares) == 22800  # Fixture A: €188 + €10 + €30
