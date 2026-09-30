# Float

Float is a money co-pilot, under construction, for students on an allowance who share a flat. It answers one question: **what can I safely spend today, after my bills, my share of the flat's costs, what I owe my flatmates, and my savings plan?**

It does this with:

- a recurrence engine for bills;
- households with shared expenses, fair cent-exact splits, simplified settle-up plans, and two-party settlement confirmation;
- goal contribution plans;
- a pace-based forecast of whether the money lasts until the next allowance.

## Project status

Version 0.2 of the requirements (30 September 2026) expands the original single-user allowance tracker after the professor's feedback that the idea and backend were too simple. The student reported the professor's approval of the revised scope on 30 September 2026. Implementation follows [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md), one tested slice per day, on the schedule in [`planned-commits.md`](planned-commits.md).

The stack is Python/FastAPI with SQLite, server-rendered pages, and (in P1) a JSON API, all in one process. It is organized as a modular monolith with three domains (Ledger, Planning, Households) plus Identity and Insights modules. Transactions are entered manually, EUR is the only currency, and the default allowance is €750 per month.

### What works so far

**Day 0 (30 September), the foundation:**
- `python app.py` starts the app, which serves a home page, `/healthz`, and a stylesheet.
- Settings are read from environment variables or an optional `.env`. Invalid values stop startup with a message naming the variable.
- The SQLite database is created on first start in WAL mode, with numbered migrations applied exactly once and the fixed categories seeded.
- The pure rules later days build on are in place and tested: exact euro parsing and formatting in integer cents, allowance-cycle dates, and recurring-bill expansion with month-end clamping.

Accounts, the ledger, bills, households, and the dashboard are not implemented yet. They arrive on the days listed in `planned-commits.md`.

## Running Float

You need Python 3.12 or newer. Development uses 3.14.7; on macOS, `/usr/bin/python3` is too old, so use a Homebrew or python.org build.

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

Then open <http://localhost:8000>. Optional settings are `PORT` (default 8000), `DATA_DIR` (default `./data`), `APP_TIMEZONE` (default `Europe/Madrid`), `COOKIE_SECURE`, `SESSION_IDLE_HOURS`, and `SESSION_MAX_DAYS`. Any of them can go in a `.env` file. The database lives at `DATA_DIR/float.sqlite3`; back it up by copying that file while the app is stopped.

## Tests and coverage

```bash
pytest
```

```bash
pytest --cov=app.shared --cov=app.db --cov=app.config --cov=app.web --cov=app.main --cov-report=term-missing
```

Measured on 30 September 2026 (Python 3.14.7, macOS): **113 tests passed**, and line coverage was **99%** (342 statements, 2 missed: the explicit `COOKIE_SECURE=false` branch in `app/config.py:68` and `SystemClock.today`). The tests include Hypothesis property tests for money round-trips, cycle dates, and recurrence.

As a check that the tests catch real bugs, five deliberate mutations were each applied and reverted: month-end clamping, weekly and monthly skip-ahead, the two-decimal limit, and the payday boundary. The suite failed for every one.

The full NFR-08 coverage command from `SRS.md` §11 applies once the domain modules exist.

## Planned documentation

- `PRD.md`: user problem, v0.1 → v0.2 changes, product principles, scope and priorities (P0/P1/P2), and success criteria.
- `SRS.md`: functional requirements, exact calculation rules with worked fixtures, state machines, architecture, schema, security, and acceptance tests.
- `AI_USAGE.md`: meaningful AI interactions and the boundary between AI drafts and the student's own explanations.
- `EXECUTION_PLAN.md`: the task-by-task implementation plan for every day, with interfaces, SQL, tests, and traceability.
- `planned-commits.md`: the daily commit schedule and the rules that keep the history honest.
- `ADR.md`: to be written as architecture decisions are finalized. Exactly five entries spanning at least three actual commit dates.

The final submission also needs a 4–5-page report and the written comprehension check.

## Assignment timeline

Deadline: **4 October 2026, 23:59**, in the course's deadline timezone.

The assignment requires at least 12 meaningful commits across at least six calendar days, pushed to GitHub on those days. No single day may contain more than 40% of the final commit total. Never fabricate or backdate commits.

Commits exist for 28 and 30 September. Nothing was pushed on 29 September, so reaching six days needs meaningful pushed work on every remaining date: 1, 2, 3, and 4 October. There is no buffer day left. Add truthful AI log entries and decisions as the work happens, not retrospectively.
