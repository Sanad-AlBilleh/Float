"""The alert rules of SRS §4.9, as a pure function of the facts (FR-32)."""

from datetime import date

import pytest

from app.insights.api import (
    AlertFacts,
    BillFact,
    BudgetFact,
    GoalFact,
    HouseholdExpenseFact,
    SettlementFact,
    UnusualFact,
    desired_alerts,
)

TODAY = date(2026, 9, 20)
CYCLE_START = date(2026, 9, 1)


def facts(**changes) -> AlertFacts:
    base = {"today": TODAY, "cycle_start": CYCLE_START}
    base.update(changes)
    return AlertFacts(**base)


def keys(**changes) -> set[str]:
    return {alert.dedupe_key for alert in desired_alerts(facts(**changes))}


def bill(due, kind="personal", number=7):
    return BillFact(kind, number, "Phone", due, 12000, "/bills")


def test_nothing_to_say():
    assert keys() == set()


@pytest.mark.parametrize("due, expected", [
    (date(2026, 9, 19), {"BILL_OVERDUE:personal:7"}),
    (date(2026, 9, 20), {"BILL_DUE_SOON:personal:7"}),
    (date(2026, 9, 23), {"BILL_DUE_SOON:personal:7"}),
    (date(2026, 9, 24), set()),
])
def test_bills_due_soon_and_overdue(due, expected):
    assert keys(bills=(bill(due),)) == expected


def test_household_bills_have_their_own_keys():
    assert keys(bills=(bill(date(2026, 9, 21), "household", 3),)) == {"BILL_DUE_SOON:household:3"}


def test_budget_states():
    budgets = (BudgetFact(1, "Groceries", "warning", 4000, 5000), BudgetFact(2, "Eating out", "over", 6000, 5000),
               BudgetFact(3, "Transport", "ok", 0, 5000))
    assert keys(budgets=budgets) == {"BUDGET_WARNING:1:2026-09-01", "BUDGET_OVER:2:2026-09-01"}


def test_pace_allowance_goal_and_settlement():
    assert keys(pace_at_risk=True, allowance_missing=True, overdue_goals=(GoalFact(4, "Laptop"),),
                settlements=(SettlementFact(9, 2, "Ben", 1000, "paid you"),)) == {
        "PACE_AT_RISK:2026-09-01", "ALLOWANCE:2026-09-01", "GOAL_OVERDUE:4", "SETTLEMENT:9"}


@pytest.mark.parametrize("day, flagged", [(date(2026, 9, 14), True), (date(2026, 9, 13), False)])
def test_unusual_expenses_from_the_last_seven_days(day, flagged):
    found = keys(unusual=(UnusualFact(5, 1400, 1000, "Eating out", day),))
    assert found == ({"UNUSUAL_EXPENSE:5"} if flagged else set())


def test_household_expense_events():
    found = desired_alerts(facts(household_expenses=(HouseholdExpenseFact(42, 1, "Ben", "Electricity", 3000),)))
    assert [(a.type, a.dedupe_key) for a in found] == [("HOUSEHOLD_EXPENSE_ADDED", "HOUSEHOLD_EXPENSE:42")]
    assert "Ben" in found[0].message and "€30.00" in found[0].message


def test_messages_are_plain_language():
    [alert] = desired_alerts(facts(bills=(bill(date(2026, 9, 19)),)))
    assert alert.severity == "critical" and "Phone" in alert.message and "€120.00" in alert.message
    assert alert.subject_url == "/bills"
