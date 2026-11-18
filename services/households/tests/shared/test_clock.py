from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.shared.clock import FixedClock, SystemClock, from_utc_text, to_utc_text

MADRID = ZoneInfo("Europe/Madrid")


def test_today_is_the_calendar_date_in_the_configured_zone():
    late_evening_utc = datetime(2026, 9, 30, 22, 30, tzinfo=UTC)  # 00:30 on 1 Oct in Madrid
    assert FixedClock(late_evening_utc, MADRID).today() == date(2026, 10, 1)
    assert FixedClock(late_evening_utc).today() == date(2026, 9, 30)


def test_fixed_clock_can_start_on_a_day_and_advance():
    clock = FixedClock.on(date(2026, 9, 20), MADRID)
    assert clock.today() == date(2026, 9, 20)
    clock.advance(days=11)
    assert clock.today() == date(2026, 10, 1)
    assert clock.now_utc().tzinfo is UTC


def test_fixed_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError, match="aware"):
        FixedClock(datetime(2026, 9, 30, 12, 0))


def test_system_clock_returns_aware_utc():
    assert SystemClock(MADRID).now_utc().tzinfo is UTC


def test_utc_text_round_trips_and_sorts():
    moment = datetime(2026, 9, 30, 8, 59, 54, 123456, tzinfo=UTC)
    text = to_utc_text(moment.astimezone(MADRID))
    assert text == "2026-09-30T08:59:54.123456Z"
    assert from_utc_text(text) == moment
    assert to_utc_text(datetime(2026, 10, 1, tzinfo=UTC)) > text
    with pytest.raises(ValueError, match="aware"):
        to_utc_text(datetime(2026, 9, 30))
