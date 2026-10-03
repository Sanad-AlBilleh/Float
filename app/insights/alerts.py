"""Alert rules (SRS §4.9): which alerts should be open for a user, as a pure function of the facts.

The application layer gathers the facts; ``app/insights/repository.py`` stores the result,
deduplicated per user by key, and resolves alerts whose condition has cleared.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.shared.money import format_money

DUE_SOON_DAYS = 3
UNUSUAL_DAYS = 7
NEVER_RESOLVES = frozenset({"HOUSEHOLD_EXPENSE_ADDED"})  # dismiss only


@dataclass(frozen=True)
class BillFact:
    kind: str  # "personal" or "household"
    occurrence_id: int
    name: str
    due_date: date
    amount_cents: int  # the user's own amount: the bill, or their share of a household bill
    url: str


@dataclass(frozen=True)
class BudgetFact:
    category_id: int
    category_name: str
    state: str | None
    consumption_cents: int
    limit_cents: int | None


@dataclass(frozen=True)
class UnusualFact:
    transaction_id: int
    amount_cents: int
    typical_cents: int
    category_name: str
    occurred_on: date


@dataclass(frozen=True)
class SettlementFact:
    settlement_id: int
    household_id: int
    other_name: str
    amount_cents: int
    verb: str  # "paid you" or "received from you"


@dataclass(frozen=True)
class HouseholdExpenseFact:
    audit_event_id: int
    household_id: int
    actor_name: str
    description: str
    share_cents: int


@dataclass(frozen=True)
class GoalFact:
    goal_id: int
    name: str


@dataclass(frozen=True)
class AlertFacts:
    today: date
    cycle_start: date
    bills: tuple[BillFact, ...] = ()  # unpaid, unskipped
    budgets: tuple[BudgetFact, ...] = ()
    pace_at_risk: bool = False
    unusual: tuple[UnusualFact, ...] = ()
    settlements: tuple[SettlementFact, ...] = ()  # pending, waiting for this user
    household_expenses: tuple[HouseholdExpenseFact, ...] = ()  # new since the user's cursor
    allowance_missing: bool = False
    overdue_goals: tuple[GoalFact, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AlertSpec:
    type: str
    dedupe_key: str
    severity: str  # info, warning, or critical
    message: str
    subject_url: str


def desired_alerts(facts: AlertFacts) -> list[AlertSpec]:
    alerts: list[AlertSpec] = []
    today = facts.today
    for bill in facts.bills:
        if bill.due_date < today:
            alerts.append(AlertSpec("BILL_OVERDUE", f"BILL_OVERDUE:{bill.kind}:{bill.occurrence_id}", "critical",
                                    f"{bill.name} ({format_money(bill.amount_cents)}) was due on "
                                    f"{bill.due_date.isoformat()} and is not paid.", bill.url))
        elif bill.due_date <= today + timedelta(days=DUE_SOON_DAYS):
            alerts.append(AlertSpec("BILL_DUE_SOON", f"BILL_DUE_SOON:{bill.kind}:{bill.occurrence_id}", "warning",
                                    f"{bill.name} ({format_money(bill.amount_cents)}) is due on "
                                    f"{bill.due_date.isoformat()}.", bill.url))
    for budget in facts.budgets:
        if budget.state == "warning":
            alerts.append(AlertSpec("BUDGET_WARNING", f"BUDGET_WARNING:{budget.category_id}:{facts.cycle_start}",
                                    "warning", f"You have used {format_money(budget.consumption_cents)} of your "
                                    f"{format_money(budget.limit_cents)} {budget.category_name} budget.", "/budgets"))
        elif budget.state == "over":
            alerts.append(AlertSpec("BUDGET_OVER", f"BUDGET_OVER:{budget.category_id}:{facts.cycle_start}",
                                    "critical", f"You are {format_money(budget.consumption_cents - budget.limit_cents)}"
                                    f" over your {budget.category_name} budget.", "/budgets"))
    if facts.pace_at_risk:
        alerts.append(AlertSpec("PACE_AT_RISK", f"PACE_AT_RISK:{facts.cycle_start}", "warning",
                                "At your usual pace, your money runs out before your next allowance.", "/forecast"))
    for expense in facts.unusual:
        if expense.occurred_on > today - timedelta(days=UNUSUAL_DAYS):
            alerts.append(AlertSpec("UNUSUAL_EXPENSE", f"UNUSUAL_EXPENSE:{expense.transaction_id}", "info",
                                    f"{format_money(expense.amount_cents)} is well above your typical "
                                    f"{format_money(expense.typical_cents)} for {expense.category_name}.",
                                    "/transactions"))
    for settlement in facts.settlements:
        alerts.append(AlertSpec("SETTLEMENT_AWAITING_YOU", f"SETTLEMENT:{settlement.settlement_id}", "warning",
                                f"{settlement.other_name} says they {settlement.verb} "
                                f"{format_money(settlement.amount_cents)}. Confirm or reject it.",
                                f"/households/{settlement.household_id}?tab=settlements"))
    for event in facts.household_expenses:
        alerts.append(AlertSpec("HOUSEHOLD_EXPENSE_ADDED", f"HOUSEHOLD_EXPENSE:{event.audit_event_id}", "info",
                                f"{event.actor_name} recorded “{event.description}”: your share is "
                                f"{format_money(event.share_cents)}.",
                                f"/households/{event.household_id}?tab=expenses"))
    if facts.allowance_missing:
        alerts.append(AlertSpec("ALLOWANCE_NOT_RECORDED", f"ALLOWANCE:{facts.cycle_start}", "info",
                                "No allowance recorded this cycle. Record it when it arrives.",
                                "/transactions/new?kind=income&source=allowance"))
    for goal in facts.overdue_goals:
        alerts.append(AlertSpec("GOAL_OVERDUE", f"GOAL_OVERDUE:{goal.goal_id}", "warning",
                                f"The target date for “{goal.name}” has passed before it was reached.", "/goals"))
    return alerts
