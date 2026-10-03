"""SRS Fixture A, "Flat 3B", built through the application layer exactly as the SRS describes it.

Today is Sunday 20 September 2026. Ana, Ben, and Carla have allowance day 1, tracking since
1 September, and a €0 opening balance. All values are synthetic test data.
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.application import bills, households, shared_money
from app.application.context import Actor
from app.households.api import SplitEntry
from app.planning.api import create_goal, move
from app.shared.clock import FixedClock
from app.shared.recurrence import Rule
from tests.conftest import MADRID
from tests.factories import add_expense, add_income, complete_setup, make_user

SEPT_1 = date(2026, 9, 1)
GROCERIES, UTILITIES, SUBSCRIPTIONS, LEISURE = 1, 5, 6, 8


@dataclass
class Flat3B:
    clock: FixedClock
    household_id: int
    ana: Actor
    ben: Actor
    carla: Actor
    phone_occurrence_id: int  # Ana's "Phone + gym", due 25 September
    internet_occurrence_id: int  # the flat's "Internet", due 28 September


def fixture_a_clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 20, 10, tzinfo=MADRID), MADRID)


def build_flat_3b(conn, clock: FixedClock | None = None) -> Flat3B:
    clock = clock or fixture_a_clock()
    people = []
    for name in ("ana", "ben", "carla"):
        user = make_user(conn, clock, name)
        complete_setup(conn, clock, user, tracking_start=SEPT_1)
        add_income(conn, clock, user, 75000, SEPT_1)
        people.append(user)
    ana, ben, carla = (Actor(user.id) for user in people)
    add_expense(conn, clock, people[0], 18800, date(2026, 9, 10), category_id=GROCERIES)
    add_expense(conn, clock, people[0], 3200, date(2026, 9, 12), category_id=LEISURE, one_off=True)  # concert
    flat = households.create_household(conn, ana, "Flat 3B", clock)
    for member in (ben, carla):
        households.join_household(conn, member, households.invite(conn, ana, flat.id, clock), clock)
    everyone = tuple(SplitEntry(actor.user_id) for actor in (ana, ben, carla))
    shared_money.record_expense(conn, ana, flat.id, shared_money.ExpenseDraft(
        3000, date(2026, 9, 19), GROCERIES, "Groceries", False, "equal", everyone), clock)
    shared_money.record_expense(conn, ben, flat.id, shared_money.ExpenseDraft(
        9000, date(2026, 9, 18), UTILITIES, "Electricity", False, "equal", everyone), clock)
    bills.add_series(conn, ana, bills.SeriesInput("Phone + gym", 12000, SUBSCRIPTIONS,
                                                  Rule("monthly", 1, date(2026, 9, 25))), clock)
    goal = create_goal(conn, user_id=ana.user_id, name="Emergency fund", target_cents=100000, now=clock.now_utc())
    move(conn, user_id=ana.user_id, goal_id=goal.id, delta_cents=5000, moved_on=date(2026, 9, 2), note="",
         now=clock.now_utc())
    internet = shared_money.add_household_bill(conn, ana, flat.id, shared_money.HouseholdBillInput(
        "Internet", 3600, UTILITIES, Rule("monthly", 1, date(2026, 9, 28)), "equal", everyone), clock)
    phone = next(o for o in bills.overview(conn, ana, clock).occurrences if o.due_date == date(2026, 9, 25))
    internet_occurrence = next(o for o in shared_money.household_bills(conn, ana, flat.id, clock).occurrences
                               if o.due_date == date(2026, 9, 28) and o.series_id == internet.id)
    return Flat3B(clock, flat.id, ana, ben, carla, phone.id, internet_occurrence.id)
