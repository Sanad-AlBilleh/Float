"""Safe-to-spend composition (SRS §4.5). Pure: callers supply integer cents and the cycle."""

from dataclasses import dataclass

from app.shared.dates import Cycle
from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS


@dataclass(frozen=True)
class SafeToSpendInputs:
    recorded_balance_cents: int
    personal_bills_cents: int = 0
    household_bill_shares_cents: int = 0
    protected_savings_cents: int = 0
    household_payables_cents: int = 0
    goal_plan_reserve_cents: int = 0

    @property
    def reserved_cents(self) -> int:
        return (
            self.personal_bills_cents
            + self.household_bill_shares_cents
            + self.protected_savings_cents
            + self.household_payables_cents
            + self.goal_plan_reserve_cents
        )


@dataclass(frozen=True)
class SafeToSpend:
    inputs: SafeToSpendInputs
    cycle: Cycle
    discretionary_cents: int

    @property
    def shortfall_cents(self) -> int:
        return max(0, -self.discretionary_cents)

    @property
    def daily_cents(self) -> int:
        return max(0, self.discretionary_cents) // self.cycle.days_remaining


@dataclass(frozen=True)
class Preview:
    cost_cents: int
    after_cents: int
    after_daily_cents: int
    after_shortfall_cents: int


def compute(inputs: SafeToSpendInputs, cycle: Cycle) -> SafeToSpend:
    return SafeToSpend(inputs, cycle, inputs.recorded_balance_cents - inputs.reserved_cents)


def preview(result: SafeToSpend, cost_cents: int) -> Preview:
    """What a purchase would leave. Works on a copy of the numbers and never writes anything."""
    if not 1 <= cost_cents <= MAX_CENTS:
        raise ValidationError.single("cost", "Enter a cost greater than zero.")
    after = result.discretionary_cents - cost_cents
    return Preview(cost_cents, after, max(0, after) // result.cycle.days_remaining, max(0, -after))
