"""SRS Fixture A, "Flat 3B", as the personal service sees it.

Today is Sunday 20 September 2026. Ana, Ben, and Carla have allowance day 1, tracking since 1 September,
and a €0 opening balance. All values are synthetic test data.

The personal half is built through this service's own code: users, setup, allowances, Ana's expenses,
her Phone + gym bill and her emergency fund, and the ledger rows the households service records here for
the two shared expenses (as it does through POST /internal/transactions). The household half lives in the
other service, so ``households`` scripts what it answers for each person: Fixture A's balances
(Ana −€10, Ben +€50, Carla −€40), the Internet bill (€36 split three ways, due 28 September) and each
person's shares of the two shared expenses.
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.application import bills
from app.application.context import Actor
from app.clients.households import ExpenseEvent, OpenBill, Position
from app.ledger.api import create_linked
from app.planning.api import create_goal, move
from app.shared.clock import FixedClock
from app.shared.recurrence import Rule
from tests.conftest import MADRID
from tests.factories import add_expense, add_income, complete_setup, make_user
from tests.fakes import ScriptedHouseholds, share

SEPT_1 = date(2026, 9, 1)
GROCERIES, UTILITIES, SUBSCRIPTIONS, LEISURE = 1, 5, 6, 8
HOUSEHOLD_ID = 1
INTERNET_OCCURRENCE_ID = 1


@dataclass
class Flat3B:
    clock: FixedClock
    household_id: int
    ana: Actor
    ben: Actor
    carla: Actor
    phone_occurrence_id: int  # Ana's "Phone + gym", due 25 September
    internet_occurrence_id: int  # the flat's "Internet", due 28 September (in the households service)
    households: ScriptedHouseholds


def fixture_a_clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 20, 10, tzinfo=MADRID), MADRID)


def _position(net_cents: int) -> Position:
    """Fixture A's household terms for one member: a €12 share of each Internet bill, and their net."""
    commitments = ((date(2026, 9, 28), 1200), (date(2026, 10, 28), 1200))
    return Position(True, 1200, max(0, -net_cents), max(0, net_cents), commitments,
                    (OpenBill(INTERNET_OCCURRENCE_ID, HOUSEHOLD_ID, "Internet (Flat 3B)", date(2026, 9, 28), 1200),))


def build_flat_3b(conn, clock: FixedClock | None = None, households: ScriptedHouseholds | None = None) -> Flat3B:
    clock = clock or fixture_a_clock()
    households = households if households is not None else ScriptedHouseholds()
    people = []
    for name in ("ana", "ben", "carla"):
        user = make_user(conn, clock, name)
        complete_setup(conn, clock, user, tracking_start=SEPT_1)
        add_income(conn, clock, user, 75000, SEPT_1)
        people.append(user)
    ana, ben, carla = (Actor(user.id) for user in people)
    add_expense(conn, clock, people[0], 18800, date(2026, 9, 10), category_id=GROCERIES)
    add_expense(conn, clock, people[0], 3200, date(2026, 9, 12), category_id=LEISURE, one_off=True)  # concert
    # The payers' ledger rows for the two shared expenses, as the households service records them here.
    for payer, cents, on, category, note in ((ana, 3000, date(2026, 9, 19), GROCERIES, "Groceries"),
                                             (ben, 9000, date(2026, 9, 18), UTILITIES, "Electricity")):
        create_linked(conn, user_id=payer.user_id, kind="expense", origin="shared", amount_cents=cents, occurred_on=on,
                      category_id=category, income_source=None, note=note, today=clock.today(), now=clock.now_utc())
    bills.add_series(conn, ana, bills.SeriesInput("Phone + gym", 12000, SUBSCRIPTIONS,
                                                  Rule("monthly", 1, date(2026, 9, 25))), clock)
    goal = create_goal(conn, user_id=ana.user_id, name="Emergency fund", target_cents=100000, now=clock.now_utc())
    move(conn, user_id=ana.user_id, goal_id=goal.id, delta_cents=5000, moved_on=date(2026, 9, 2), note="",
         now=clock.now_utc())
    for actor, net in ((ana, -1000), (ben, 5000), (carla, -4000)):
        households.positions[actor.user_id] = _position(net)
        households.share_rows[actor.user_id] = [share(1000, date(2026, 9, 19), GROCERIES),
                                                share(3000, date(2026, 9, 18), UTILITIES)]
    # The two shared expenses, as audit events 5 and 6 of the households service, for the other members.
    for event_id, payer, description, recipients in ((5, ana, "Groceries", (ben, carla)),
                                                     (6, ben, "Electricity", (ana, carla))):
        cents = 1000 if description == "Groceries" else 3000
        for recipient in recipients:
            households.expense_events.append((recipient.user_id, ExpenseEvent(
                event_id, HOUSEHOLD_ID, payer.user_id, description, cents)))
    phone = next(o for o in bills.overview(conn, ana, clock).occurrences if o.due_date == date(2026, 9, 25))
    return Flat3B(clock, HOUSEHOLD_ID, ana, ben, carla, phone.id, INTERNET_OCCURRENCE_ID, households)
