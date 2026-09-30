"""Injectable time, so every date-dependent rule can be tested (SRS §2, §6.4)."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol, Self
from zoneinfo import ZoneInfo

_UTC_TEXT = "%Y-%m-%dT%H:%M:%S.%fZ"


class Clock(Protocol):
    def now_utc(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    """Real time. ``today`` is the calendar date in the configured time zone."""

    def __init__(self, timezone: ZoneInfo) -> None:
        self._timezone = timezone

    def now_utc(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return datetime.now(self._timezone).date()


class FixedClock:
    """A controllable clock for tests."""

    def __init__(self, now: datetime, timezone: ZoneInfo | None = None) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = now.astimezone(UTC)
        self._timezone = timezone or ZoneInfo("UTC")

    @classmethod
    def on(cls, day: date, timezone: ZoneInfo | None = None) -> Self:
        """Noon on ``day`` in ``timezone``, far from midnight, so ``today()`` is ``day``."""
        zone = timezone or ZoneInfo("UTC")
        return cls(datetime(day.year, day.month, day.day, 12, tzinfo=zone), zone)

    def now_utc(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(self._timezone).date()

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


def to_utc_text(moment: datetime) -> str:
    """Sortable UTC text for timestamp columns, e.g. ``2026-09-30T08:59:54.123456Z``."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).strftime(_UTC_TEXT)


def from_utc_text(text: str) -> datetime:
    return datetime.strptime(text, _UTC_TEXT).replace(tzinfo=UTC)
