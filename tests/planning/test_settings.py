"""Planning settings captured during setup (FR-05) and the allowance cycle they define (§4.1)."""

from datetime import date

import pytest

from app.planning.api import get_cycle, get_settings, save_settings, update_planned_allowance
from app.shared.errors import ConflictError, ValidationError
from tests.factories import make_user


def test_settings_are_saved_once_and_read_back(conn, clock):
    ana = make_user(conn, clock)
    saved = save_settings(conn, user_id=ana.id, allowance_day=1, planned_allowance_cents=75000)
    assert get_settings(conn, ana.id) == saved
    with pytest.raises(ConflictError):
        save_settings(conn, user_id=ana.id, allowance_day=2, planned_allowance_cents=1)


@pytest.mark.parametrize(
    "day, cents, fields",
    [(0, 75000, {"allowance_day"}), (32, 75000, {"allowance_day"}), (1, 0, {"planned_allowance"}),
     (1, 100_000_001, {"planned_allowance"}), (0, 0, {"allowance_day", "planned_allowance"})],
)
def test_invalid_settings_name_every_field(conn, clock, day, cents, fields):
    ana = make_user(conn, clock)
    with pytest.raises(ValidationError) as error:
        save_settings(conn, user_id=ana.id, allowance_day=day, planned_allowance_cents=cents)
    assert set(error.value.errors) == fields


def test_the_planned_allowance_stays_editable(conn, clock):
    ana = make_user(conn, clock)
    save_settings(conn, user_id=ana.id, allowance_day=1, planned_allowance_cents=75000)
    assert update_planned_allowance(conn, user_id=ana.id, planned_allowance_cents=80000).planned_allowance_cents == 80000
    with pytest.raises(ValidationError):
        update_planned_allowance(conn, user_id=ana.id, planned_allowance_cents=0)


def test_the_cycle_follows_the_allowance_day(conn, clock):
    ana = make_user(conn, clock)
    save_settings(conn, user_id=ana.id, allowance_day=31, planned_allowance_cents=75000)
    cycle = get_cycle(conn, user_id=ana.id, today=date(2027, 1, 31))
    assert (cycle.start, cycle.next_allowance, cycle.days_remaining) == (date(2027, 1, 31), date(2027, 2, 28), 28)


def test_the_cycle_requires_setup(conn, clock):
    ana = make_user(conn, clock)
    with pytest.raises(ConflictError):
        get_cycle(conn, user_id=ana.id, today=clock.today())
