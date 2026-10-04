"""NFR-05 / AT-31 performance smoke test.

Builds the SRS synthetic dataset in a temporary directory: a 3-member household, 5,000 personal
transactions per member, 1,000 shared expenses, and 20 bill series. It then times app start-up and
50 dashboard requests (materialization and alert evaluation included) through the real app. Run it
from the repository root:

    python scripts/perf_smoke.py
"""

import platform
import statistics
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.application import bills, households, shared_money  # noqa: E402
from app.application.context import Actor  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.db.migrations import initialize_database  # noqa: E402
from app.db.unit_of_work import transaction  # noqa: E402
from app.households.api import SplitEntry  # noqa: E402
from app.ledger.api import TransactionDraft, create_manual  # noqa: E402
from app.main import create_app  # noqa: E402
from app.shared.recurrence import Rule  # noqa: E402
from tests.factories import PASSWORD, complete_setup, make_user  # noqa: E402

REQUESTS = 50


def build(db_path: Path, clock) -> None:
    initialize_database(db_path)
    conn = connect(db_path)
    try:
        today = clock.today()
        start = today - timedelta(days=200)
        people = []
        for name in ("ana", "ben", "carla"):
            user = make_user(conn, clock, name)
            complete_setup(conn, clock, user, tracking_start=start, opening_cents=500000)
            people.append(user)
            with transaction(conn):
                for number in range(5000):
                    draft = TransactionDraft("expense", 100 + number % 2000, start + timedelta(days=number % 200),
                                             category_id=1 + number % 11)
                    create_manual(conn, user_id=user.id, draft=draft, today=today, now=clock.now_utc())
        actors = [Actor(user.id) for user in people]
        flat = households.create_household(conn, actors[0], "Perf flat", clock)
        for actor in actors[1:]:
            households.join_household(conn, actor, households.invite(conn, actors[0], flat.id, clock), clock)
        everyone = tuple(SplitEntry(actor.user_id) for actor in actors)
        for number in range(1000):
            payer = actors[number % 3]
            shared_money.record_expense(conn, payer, flat.id, shared_money.ExpenseDraft(
                300 + number % 900, start + timedelta(days=number % 200), 1 + number % 11, f"Shared {number}", False,
                "equal", everyone), clock)
        for number in range(20):
            bills.add_series(conn, actors[0], bills.SeriesInput(f"Bill {number}", 1000 + number, 6,
                                                                Rule("monthly", 1, start + timedelta(days=number))),
                             clock)
    finally:
        conn.close()


def main() -> None:
    from app.shared.clock import SystemClock
    from zoneinfo import ZoneInfo

    clock = SystemClock(ZoneInfo("Europe/Madrid"))
    with tempfile.TemporaryDirectory() as folder:
        settings = Settings(data_dir=Path(folder))
        began = time.perf_counter()
        build(settings.db_path, clock)
        print(f"dataset built in {time.perf_counter() - began:.1f} s")
        check = connect(settings.db_path)
        counts = {table: check.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("users", "transactions", "shared_expenses", "bill_series", "memberships")}
        check.close()
        print(f"rows: {counts}")
        began = time.perf_counter()
        app = create_app(settings, clock)
        with TestClient(app) as browser:
            assert browser.get("/healthz").status_code == 200
            ready = time.perf_counter() - began
            token = browser.get("/login").text.split('name="csrf_token" value="')[1].split('"')[0]
            browser.post("/login", data={"username": "ana", "password": PASSWORD, "csrf_token": token},
                         headers={"Origin": "http://testserver"})
            timings = []
            for _ in range(REQUESTS):
                began = time.perf_counter()
                response = browser.get("/")
                timings.append((time.perf_counter() - began) * 1000)
                assert response.status_code == 200 and "Safe to spend today" in response.text
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        print(f"machine: {platform.platform()}, Python {platform.python_version()}, {platform.machine()}")
        print(f"ready in {ready * 1000:.0f} ms (limit 5,000 ms)")
        print(f"dashboard over {REQUESTS} requests: median {statistics.median(timings):.0f} ms, "
              f"p95 {p95:.0f} ms, max {timings[-1]:.0f} ms (limit p95 500 ms)")
        print("PASS" if p95 < 500 and ready < 5 else "FAIL")


if __name__ == "__main__":
    main()
