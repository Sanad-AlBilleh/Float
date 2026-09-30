"""Recurrence rules for bills (SRS §4.2). Pure functions with no I/O."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.shared.dates import add_months, scheduled_date
from app.shared.errors import ValidationError

FREQUENCIES = ("once", "weekly", "monthly")
MAX_INTERVAL = {"once": 1, "weekly": 52, "monthly": 12}
MAX_COUNT = 500


@dataclass(frozen=True)
class Rule:
    """``freq`` every ``interval`` periods from ``anchor``, ending by ``until`` or ``count``."""

    freq: str
    interval: int
    anchor: date
    until: date | None = None
    count: int | None = None

    def __post_init__(self) -> None:
        errors: dict[str, str] = {}
        if self.freq not in FREQUENCIES:
            errors["freq"] = "Choose once, weekly, or monthly."
        elif not 1 <= self.interval <= MAX_INTERVAL[self.freq]:
            errors["interval"] = (
                "A one-off bill has no repeat interval."
                if self.freq == "once"
                else f"Choose an interval between 1 and {MAX_INTERVAL[self.freq]}."
            )
        if self.until is not None and self.count is not None:
            errors["until"] = "Choose an end date or a number of occurrences, not both."
        elif self.freq == "once" and (self.until is not None or self.count is not None):
            errors["until"] = "A one-off bill cannot have an end condition."
        elif self.until is not None and self.until < self.anchor:
            errors["until"] = "The end date cannot be before the first date."
        if self.count is not None and not 1 <= self.count <= MAX_COUNT:
            errors["count"] = f"Choose between 1 and {MAX_COUNT} occurrences."
        if errors:
            raise ValidationError(errors)


def candidate(rule: Rule, k: int) -> date:
    """The k-th date of the rule, ignoring end conditions; k = 0 is the anchor."""
    if rule.freq == "weekly":
        return rule.anchor + timedelta(weeks=rule.interval * k)
    if rule.freq == "monthly":
        year, month = add_months(rule.anchor.year, rule.anchor.month, rule.interval * k)
        return scheduled_date(year, month, rule.anchor.day)
    return rule.anchor


def _first_index_at_or_before(rule: Rule, day: date) -> int:
    """A k whose candidate is not after ``day`` (0 if ``day`` precedes the anchor), to skip ahead."""
    if day <= rule.anchor or rule.freq == "once":
        return 0
    if rule.freq == "weekly":
        return (day - rule.anchor).days // (7 * rule.interval)
    months = (day.year - rule.anchor.year) * 12 + (day.month - rule.anchor.month)
    return max(0, months // rule.interval - 1)


def expand(rule: Rule, window_start: date, window_end_exclusive: date) -> list[date]:
    """Valid occurrence dates ``d`` with ``window_start <= d < window_end_exclusive``, ascending.

    Candidates are counted from the anchor, so a count-limited rule yields the same dates
    whichever window is requested.
    """
    dates: list[date] = []
    k = _first_index_at_or_before(rule, window_start)
    while not (rule.freq == "once" and k > 0) and (rule.count is None or k < rule.count):
        current = candidate(rule, k)
        if (rule.until is not None and current > rule.until) or current >= window_end_exclusive:
            break
        if current >= window_start:
            dates.append(current)
        k += 1
    return dates


def count_before(rule: Rule, day: date) -> int:
    """How many valid occurrences fall strictly before ``day``."""
    return len(expand(rule, rule.anchor, day))
