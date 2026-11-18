"""Pure planning rules."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date

from app.shared.dates import Cycle, allowance_dates
from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS


def validate_settings(*, allowance_day: int, planned_allowance_cents: int) -> None:
    errors: dict[str, str] = {}
    if not 1 <= allowance_day <= 31:
        errors["allowance_day"] = "Choose a day between 1 and 31."
    try:
        validate_planned_allowance(planned_allowance_cents)
    except ValidationError as error:
        errors.update(error.errors)
    if errors:
        raise ValidationError(errors)


def validate_planned_allowance(cents: int) -> None:
    if not 1 <= cents <= MAX_CENTS:
        raise ValidationError.single("planned_allowance", "Enter an amount between €0.01 and €1,000,000.00.")


NAME_LIMIT = 100


def validate_bill(*, name: str, amount_cents: int, category_id: int | None, category_ids: Collection[int]) -> None:
    errors: dict[str, str] = {}
    if not 1 <= len(name) <= NAME_LIMIT:
        errors["name"] = f"Enter a name of 1 to {NAME_LIMIT} characters."
    if not 1 <= amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    if category_id not in category_ids:
        errors["category_id"] = "Choose a category."
    if errors:
        raise ValidationError(errors)


def validate_anchor(anchor: date, *, tracking_start: date) -> None:
    if anchor < tracking_start:
        raise ValidationError.single(
            "anchor_date", f"Choose a first date on or after {tracking_start.isoformat()}, when tracking started."
        )


def occurrence_status(occurrence, *, today: date, next_allowance: date) -> str:
    """FR-11: derived on read from the payment link, the skip mark, and the due date."""
    if occurrence.paid_transaction_id is not None:
        return "paid"
    if occurrence.skipped:
        return "skipped"
    if occurrence.due_date < today:
        return "overdue"
    if occurrence.due_date < next_allowance:
        return "reserved"
    return "upcoming"


@dataclass(frozen=True)
class GoalPlan:
    cycles_left: int
    planned_cents: int  # this cycle's contribution, fixed for the whole cycle
    pending_reserve_cents: int  # the part of the plan not yet protected this cycle
    status: str  # "complete", "no_target_date", "overdue", "on_plan", or "behind"


def goal_plan(*, target_cents: int, target_date: date | None, movements: Iterable[tuple[date, int]], cycle: Cycle,
              allowance_day: int, auto_reserve: bool = False) -> GoalPlan:
    """SRS §4.6. Movements after today are ignored. An auto-reserve goal is on plan while this cycle's pending
    amount is held back from safe-to-spend; a manual goal is behind until the user protects it."""
    movements = list(movements)
    protected_now = sum(delta for moved_on, delta in movements if moved_on <= cycle.today)
    if protected_now >= target_cents:
        return GoalPlan(0, 0, 0, "complete")
    if target_date is None:
        return GoalPlan(0, 0, 0, "no_target_date")
    cycles_left = len(allowance_dates(cycle.start, target_date, allowance_day))
    if cycles_left == 0:
        return GoalPlan(0, 0, 0, "overdue")
    protected_at_start = sum(delta for moved_on, delta in movements if moved_on < cycle.start)
    planned = -(-max(0, target_cents - protected_at_start) // cycles_left)  # ceiling division
    this_cycle = sum(delta for moved_on, delta in movements if cycle.start <= moved_on <= cycle.today)
    pending = min(planned, max(0, planned - this_cycle), max(0, target_cents - protected_now))
    return GoalPlan(cycles_left, planned, pending, "on_plan" if pending == 0 or auto_reserve else "behind")


def next_cycle_contribution(plan: GoalPlan, *, target_cents: int, protected_now_cents: int) -> int:
    """Next cycle's planned contribution, for the next-cycle outlook (SRS §4.7)."""
    if plan.cycles_left <= 1:
        return 0
    remaining = max(0, target_cents - protected_now_cents - plan.pending_reserve_cents)
    return -(-remaining // (plan.cycles_left - 1))


def budget_state(consumption_cents: int, limit_cents: int | None) -> str | None:
    """FR-31: ``ok``, ``warning`` from 80%, ``over`` above 100%; a zero limit is over for any spending."""
    if limit_cents is None:
        return None
    if consumption_cents > limit_cents:
        return "over"
    if limit_cents > 0 and consumption_cents * 10 >= limit_cents * 8:
        return "warning"
    return "ok"


def validate_limit(limit_cents: int) -> None:
    if not 0 <= limit_cents <= MAX_CENTS:
        raise ValidationError.single("limit", "Enter a limit between €0.00 and €1,000,000.00.")
