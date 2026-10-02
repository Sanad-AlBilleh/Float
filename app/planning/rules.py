"""Pure planning rules."""

from collections.abc import Collection
from datetime import date

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
