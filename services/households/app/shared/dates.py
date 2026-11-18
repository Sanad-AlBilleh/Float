"""Calendar rules for allowance cycles (SRS §4.1)."""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.shared.errors import ValidationError

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
EARLIEST = date(2000, 1, 1)  # every date Float accepts lies in this range, so date arithmetic cannot overflow
LATEST = date(2100, 12, 31)
RANGE_MESSAGE = f"Enter a date between {EARLIEST.isoformat()} and {LATEST.isoformat()}."


def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(year: int, month: int, months: int) -> tuple[int, int]:
    """Move a (year, month) pair by ``months`` (may be negative), carrying the year."""
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def scheduled_date(year: int, month: int, day: int) -> date:
    """Day ``day`` of the month, clamped to the month's last day (31 → 28 February)."""
    return date(year, month, min(day, last_day_of_month(year, month)))


def validate_allowance_day(day: int) -> int:
    if not 1 <= day <= 31:
        raise ValidationError.single("allowance_day", "Choose a day between 1 and 31.")
    return day


@dataclass(frozen=True)
class Cycle:
    """The allowance cycle containing ``today`` (SRS §4.1)."""

    today: date
    start: date  # latest scheduled allowance date on or before today
    next_allowance: date  # earliest scheduled allowance date after today
    horizon_end: date  # the scheduled date after next_allowance; exclusive end of the horizon

    @property
    def days_remaining(self) -> int:
        return (self.next_allowance - self.today).days


def cycle_for(today: date, allowance_day: int) -> Cycle:
    validate_allowance_day(allowance_day)
    this_month = scheduled_date(today.year, today.month, allowance_day)
    if this_month <= today:
        start = this_month
        next_allowance = scheduled_date(*add_months(today.year, today.month, 1), allowance_day)
    else:
        start = scheduled_date(*add_months(today.year, today.month, -1), allowance_day)
        next_allowance = this_month
    horizon_end = scheduled_date(*add_months(next_allowance.year, next_allowance.month, 1), allowance_day)
    return Cycle(today=today, start=start, next_allowance=next_allowance, horizon_end=horizon_end)


def allowance_dates(start: date, end_exclusive: date, allowance_day: int) -> list[date]:
    """Every scheduled allowance date ``d`` with ``start <= d < end_exclusive``, in order."""
    validate_allowance_day(allowance_day)
    dates: list[date] = []
    year, month = start.year, start.month
    while (candidate := scheduled_date(year, month, allowance_day)) < end_exclusive:
        if candidate >= start:
            dates.append(candidate)
        year, month = add_months(year, month, 1)
    return dates


def parse_iso_date(text: str | None, *, field: str = "date") -> date:
    """Parse exactly ``YYYY-MM-DD``; other ISO forms (week dates, compact dates) are rejected."""
    raw = (text or "").strip()
    try:
        if not _ISO_DATE.fullmatch(raw):
            raise ValueError(raw)
        day = date.fromisoformat(raw)
    except ValueError:
        raise ValidationError.single(field, "Enter a date as YYYY-MM-DD.") from None
    if not EARLIEST <= day <= LATEST:
        raise ValidationError.single(field, RANGE_MESSAGE)
    return day
