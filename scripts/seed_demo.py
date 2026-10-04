"""Fill a fresh Float database with a month of realistic demo data, for showing every feature.

Usage (from the repository root, on a database the app is NOT using yet):

    python scripts/seed_demo.py DATA_DIR USERNAME "Display Name" PASSWORD

It creates the main account plus two flatmates (``lucia_demo`` and ``marco_demo``, same password) and
replays 1 September to today through the application layer, one day at a time, so every record,
audit event, and activity line carries a believable date:

- allowances, other income, and about 60 everyday expenses (one unusual, some one-off);
- a custom category, four recurring bills (paid, overdue, due soon), and four savings goals;
- budget limits (one over, one at 80%, one this-cycle override);
- a household with invitation codes (two used, one still open), shared expenses with every split
  method, three household bills, a confirmed settlement, and one waiting for the main user;
- alerts evaluated for today.

All amounts are invented demo data, not anyone's real finances.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import (  # noqa: E402
    accounts,
    alerts,
    bills,
    budgets,
    categories,
    goals,
    households,
    setup,
    shared_money,
    transactions,
)
from app.application.context import Actor  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.db.migrations import initialize_database  # noqa: E402
from app.households.api import SplitEntry  # noqa: E402
from app.ledger.api import TransactionDraft  # noqa: E402
from app.shared.clock import FixedClock  # noqa: E402
from app.shared.recurrence import Rule  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")
GROCERIES, EATING_OUT, TRANSPORT, HOUSING, UTILITIES, SUBSCRIPTIONS = 1, 2, 3, 4, 5, 6
STUDY, LEISURE, HEALTH, TRAVEL, OTHER = 7, 8, 9, 10, 11


def on(day: date, hour: int = 12) -> FixedClock:
    return FixedClock(datetime(day.year, day.month, day.day, hour, tzinfo=MADRID), MADRID)


def main(data_dir: str, username: str, display_name: str, password: str) -> None:
    db_path = Path(data_dir) / "float.sqlite3"
    if db_path.exists():
        raise SystemExit(f"{db_path} already exists: seed a fresh data directory.")
    initialize_database(db_path)
    conn = connect(db_path)
    today = datetime.now(MADRID).date()
    sep1 = date(today.year, 9, 1) if today.month >= 9 else date(today.year - 1, 9, 1)
    day = lambda n: sep1 + timedelta(days=n - 1)  # noqa: E731 - "day(15)" reads as 15 September
    max_age = timedelta(days=14)

    def person(name: str, shown: str, opening: int, when: date, savings: int = 0) -> Actor:
        session, _ = accounts.register_account(conn, username=name, display_name=shown, password=password,
                                               clock=on(when, 9), max_age=max_age)
        actor = Actor(session.user.id)
        setup.complete_setup(conn, actor, setup.SetupInput(sep1, opening, 1, 120000, False, savings), on(when, 9))
        return actor

    def spend(actor: Actor, n: int, cents: int, category: int, note: str, one_off: bool = False) -> None:
        if day(n) <= today:
            transactions.add_transaction(conn, actor, TransactionDraft("expense", cents, day(n), category,
                                                                       one_off=one_off, note=note), on(day(n), 19))

    def earn(actor: Actor, n: int, cents: int, source: str, note: str) -> None:
        if day(n) <= today:
            transactions.add_transaction(conn, actor, TransactionDraft("income", cents, day(n), income_source=source,
                                                                       note=note), on(day(n), 10))

    # 1–3 September: accounts, setup, categories, budgets, bills, goals, and the household -----------------
    borja = person(username, display_name, 50000, day(1), savings=10000)
    lucia = person("lucia_demo", "Lucía Martín", 45000, day(1))
    marco = person("marco_demo", "Marco Rossi", 25000, day(2))
    for actor in (borja, lucia, marco):
        earn(actor, 1, 120000, "allowance", "September allowance")
    gym = categories.add_category(conn, borja, "Gym", on(day(1), 11))
    categories.add_category(conn, borja, "Gifts", on(day(1), 11))
    for category_id, limit, scope in ((GROCERIES, 22000, "template"), (EATING_OUT, 9000, "template"),
                                      (TRANSPORT, 4000, "template"), (LEISURE, 6000, "template"),
                                      (gym.id, 4000, "template")):
        budgets.set_limit(conn, borja, category_id, limit, scope, on(day(2), 9))
    phone = bills.add_series(conn, borja, bills.SeriesInput("Phone plan", 1500, UTILITIES,
                                                            Rule("monthly", 1, day(6))), on(day(2), 10))
    gym_bill = bills.add_series(conn, borja, bills.SeriesInput("Gym membership", 3500, gym.id,
                                                               Rule("monthly", 1, day(10))), on(day(2), 10))
    spotify = bills.add_series(conn, borja, bills.SeriesInput("Spotify", 1099, SUBSCRIPTIONS,
                                                              Rule("monthly", 1, day(20))), on(day(2), 10))
    bills.add_series(conn, borja, bills.SeriesInput("Netflix", 799, SUBSCRIPTIONS,
                                                    Rule("monthly", 1, day(33))), on(day(2), 10))
    laptop = goals.add_goal(conn, borja, goals.GoalInput("New laptop", 90000, date(sep1.year + 1, 3, 1), 1, True),
                            on(day(2), 11))
    lisbon = goals.add_goal(conn, borja, goals.GoalInput("Summer trip to Lisbon", 60000, date(sep1.year + 1, 6, 1), 2,
                                                         False), on(day(2), 11))
    emergency = goals.add_goal(conn, borja, goals.GoalInput("Emergency fund", 50000, None, 1, False), on(day(2), 11))
    flat = households.create_household(conn, borja, "Piso Ruzafa", on(day(2), 12))
    households.join_household(conn, lucia, households.invite(conn, borja, flat.id, on(day(2), 12)), on(day(2), 18))
    households.join_household(conn, marco, households.invite(conn, borja, flat.id, on(day(3), 9)), on(day(3), 20))
    three = (borja, lucia, marco)
    everyone = tuple(SplitEntry(a.user_id) for a in three)
    internet = shared_money.add_household_bill(conn, borja, flat.id, shared_money.HouseholdBillInput(
        "Internet", 4500, UTILITIES, Rule("monthly", 1, day(15)), "equal", everyone), on(day(3), 21))
    electricity = shared_money.add_household_bill(conn, borja, flat.id, shared_money.HouseholdBillInput(
        "Electricity", 6000, UTILITIES, Rule("monthly", 1, day(25)), "shares",
        tuple(SplitEntry(a.user_id, w) for a, w in zip(three, (2, 1, 1)))), on(day(3), 21))
    rent = shared_money.add_household_bill(conn, borja, flat.id, shared_money.HouseholdBillInput(
        "Rent", 90000, HOUSING, Rule("monthly", 1, day(28)), "percentage",
        tuple(SplitEntry(a.user_id, bp) for a, bp in zip(three, (4000, 3000, 3000)))), on(day(3), 21))

    # September, day by day ------------------------------------------------------------------------------
    everyday = [
        (2, 2340, GROCERIES, "Weekly shop at Mercadona"), (3, 450, TRANSPORT, "Metro card top-up"),
        (4, 1180, EATING_OUT, "Ramen with classmates"), (5, 3200, STUDY, "Statistics textbook"),
        (6, 980, LEISURE, "Cinema"), (8, 1860, GROCERIES, "Lidl"), (9, 320, EATING_OUT, "Coffee and croissant"),
        (11, 2750, HEALTH, "Pharmacy"), (12, 1400, EATING_OUT, "Burger night"), (13, 2100, GROCERIES, "Market"),
        (14, 4500, LEISURE, "Festival ticket"), (15, 560, TRANSPORT, "Bus to the coast"),
        (16, 1990, GROCERIES, "Weekly shop"), (17, 890, EATING_OUT, "Tapas"), (18, 1250, STUDY, "Printing and notebooks"),
        (19, 760, EATING_OUT, "Lunch at uni"), (20, 2410, GROCERIES, "Mercadona"), (21, 1500, LEISURE, "Bowling"),
        (22, 940, EATING_OUT, "Pizza slice"), (23, 2300, GROCERIES, "Weekly shop"), (24, 1100, EATING_OUT, "Sushi"),
        (25, 3990, OTHER, "Birthday present for Lucía"), (26, 650, TRANSPORT, "Taxi home"),
        (27, 1720, GROCERIES, "Market"), (29, 1290, EATING_OUT, "Kebab and drinks"), (30, 2050, GROCERIES, "Lidl"),
        (32, 2600, GROCERIES, "October first shop"), (32, 880, EATING_OUT, "Coffee with Marco"),
        (33, 6800, EATING_OUT, "Fancy dinner out"), (33, 450, TRANSPORT, "Metro card top-up"),
        (34, 1450, LEISURE, "Museum and snacks"), (32, 3500, LEISURE, "Concert tickets"),
        (34, 900, EATING_OUT, "Brunch"),
    ]
    for n, cents, category, note in everyday:
        spend(borja, n, cents, category, note)
    spend(borja, 7, 18900, TRAVEL, "Weekend flight to Mallorca", one_off=True)
    earn(borja, 15, 12000, "other", "Private tutoring")
    for n, cents, category, note in [(5, 2600, GROCERIES, "Weekly shop"), (12, 1500, EATING_OUT, "Dinner"),
                                     (20, 3400, LEISURE, "Concert"), (27, 2200, GROCERIES, "Market")]:
        spend(lucia, n, cents, category, note)
        spend(marco, n + 1, cents - 300, category, note)

    def pay(series_id: int, n: int) -> None:
        row = next(o for o in bills.overview(conn, borja, on(day(n))).occurrences if o.series_id == series_id)
        bills.pay_occurrence(conn, borja, row.id, row.version, day(n), on(day(n), 13))

    pay(phone.id, 6)
    pay(gym_bill.id, 10)
    pay(spotify.id, 20)

    def pay_household(actor: Actor, series_id: int, n: int) -> None:
        row = next(o for o in shared_money.household_bills(conn, actor, flat.id, on(day(n))).occurrences
                   if o.series_id == series_id and o.status != "paid")
        shared_money.pay_household_occurrence(conn, actor, row.id, row.version, day(n), on(day(n), 14))

    pay_household(marco, internet.id, 15)
    pay_household(lucia, electricity.id, 25)
    pay_household(borja, rent.id, 28)

    def shared(actor: Actor, n: int, cents: int, category: int, text: str, method: str = "equal",
               values=(None, None, None), people=three) -> None:
        entries = tuple(SplitEntry(a.user_id, v) for a, v in zip(people, values))
        shared_money.record_expense(conn, actor, flat.id, shared_money.ExpenseDraft(
            cents, day(n), category, text, False, method, entries), on(day(n), 20))

    shared(borja, 4, 5400, GROCERIES, "Big flat shop")
    shared(lucia, 9, 2100, HOUSING, "Cleaning supplies")
    shared(marco, 13, 4800, EATING_OUT, "Paella night", "shares", (2, 1, 1))
    shared(borja, 19, 3000, LEISURE, "Board game", "exact", (1000, 1000, 1000))
    shared(lucia, 24, 6300, GROCERIES, "Costco run", "percentage", (4000, 3000, 3000))
    shared(marco, 30, 1800, HOUSING, "Light bulbs and batteries", people=(borja, marco), values=(None, None))
    if day(33) <= today:
        shared(lucia, 33, 3600, EATING_OUT, "Pizza for the flat")

    settlement, _ = shared_money.record_settlement(conn, lucia, flat.id, lucia.user_id, borja.user_id, 30000, day(29),
                                                   on(day(29), 21))
    shared_money.confirm_settlement(conn, borja, settlement.id, settlement.version, on(day(29), 22))
    pending_day = min(day(34), today)
    shared_money.record_settlement(conn, marco, flat.id, marco.user_id, borja.user_id, 25000, pending_day,
                                   on(pending_day, 9))
    for goal, n, cents in ((laptop, 2, 5000), (laptop, 16, 3000), (lisbon, 9, 4000), (lisbon, 23, 2000),
                           (emergency, 5, 10000), (emergency, 30, 5000)):
        goals.move_money(conn, borja, goal.id, cents, on(day(n), 21))

    # 1 October onward: the new cycle ---------------------------------------------------------------------
    if day(31) <= today:
        for actor in three:
            earn(actor, 31, 120000, "allowance", "October allowance")
        budgets.set_limit(conn, borja, TRAVEL, 5000, "cycle", on(day(31), 9))
    households.invite(conn, borja, flat.id, on(today, 8))  # an unused code, listed on the Members tab
    conn.close()
    conn = connect(db_path)
    for actor in three:
        alerts.evaluate(conn, actor.user_id, on(today, 12))
    conn.close()
    print(f"Seeded {db_path}: log in as {username} (flatmates lucia_demo and marco_demo, same password).")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
