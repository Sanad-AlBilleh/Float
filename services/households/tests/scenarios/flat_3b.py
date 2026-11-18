"""SRS Fixture A, "Flat 3B", as the households service sees it.

Today is Sunday 20 September 2026. Ana (1), Ben (2) and Carla (3) track from 1 September with allowance
day 1 (their profiles live in the personal service, here the in-memory stand-in). Ana owns Flat 3B; Ben
and Carla joined. Ana paid €30 of groceries and Ben €90 of electricity, both split equally, and the flat
shares a €36 Internet bill due on the 28th. Balances: Ana −€10, Ben +€50, Carla −€40.
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.application import households, shared_money
from app.application.context import Actor
from app.households.api import SplitEntry
from app.shared.clock import FixedClock
from app.shared.recurrence import Rule
from tests.conftest import MADRID
from tests.factories import make_member
from tests.fakes import FakePersonal

GROCERIES, UTILITIES = 1, 5
TODAY = date(2026, 9, 20)


@dataclass
class Flat3B:
    clock: FixedClock
    household_id: int
    ana: Actor
    ben: Actor
    carla: Actor
    internet_occurrence_id: int
    personal: FakePersonal


def build_flat_3b(conn, personal: FakePersonal) -> Flat3B:
    clock = FixedClock(datetime(2026, 9, 20, 10, tzinfo=MADRID), MADRID)
    personal.today = clock.today()
    ana, ben, carla = (make_member(personal, i, name) for i, name in ((1, "Ana"), (2, "Ben"), (3, "Carla")))
    flat = households.create_household(conn, ana, "Flat 3B", clock)
    for member in (ben, carla):
        households.join_household(conn, personal, member, households.invite(conn, ana, flat.id, clock), clock)
    everyone = tuple(SplitEntry(actor.user_id) for actor in (ana, ben, carla))
    shared_money.record_expense(conn, personal, ana, flat.id, shared_money.ExpenseDraft(
        3000, date(2026, 9, 19), GROCERIES, "Groceries", False, "equal", everyone), clock)
    shared_money.record_expense(conn, personal, ben, flat.id, shared_money.ExpenseDraft(
        9000, date(2026, 9, 18), UTILITIES, "Electricity", False, "equal", everyone), clock)
    internet = shared_money.add_household_bill(conn, personal, ana, flat.id, shared_money.HouseholdBillInput(
        "Internet", 3600, UTILITIES, Rule("monthly", 1, date(2026, 9, 28)), "equal", everyone), clock)
    occurrence = next(o for o in shared_money.household_bills(conn, personal, ana, flat.id, clock).occurrences
                      if o.due_date == date(2026, 9, 28) and o.series_id == internet.id)
    return Flat3B(clock, flat.id, ana, ben, carla, occurrence.id, personal)
