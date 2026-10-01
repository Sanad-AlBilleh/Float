"""Pure planning rules."""

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
