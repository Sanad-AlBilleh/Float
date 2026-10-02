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
- `python app.py` starts the app.
- Settings are read from the environment or an optional `.env`, and invalid values stop startup with a clear message.
- The SQLite database runs in WAL mode, with numbered migrations applied exactly once.
- The pure rules later days build on are tested: exact euro parsing in integer cents, allowance-cycle dates, and recurring-bill expansion.

**Day 1 (1 October), accounts and the personal ledger:**
- **Accounts:** create an account, log in and out, and change your password. Passwords are stored as scrypt hashes. Sessions expire after 48 idle hours or 14 days, and changing your password signs out your other browsers. Five failed logins lock a username, and twenty lock an address, for 15 minutes from the last failure; the message shows the minutes left.
- **Security:** every form is protected against cross-site requests. Pages send security headers and a request ID. Each request writes one log line containing no secrets. Errors show friendly pages, and other people's records answer "not found".
- **Setup:** enter your start date, the money you have now, whether this cycle's allowance is already in that amount, your allowance day, and your planned allowance (default €750). The start date, opening balance, and allowance day are fixed afterwards; the planned allowance can be changed in Settings.
- **Transactions:** record, edit, and delete income and expenses. Amounts like `12,50` and `1 234,56` are read exactly, while ambiguous input such as `12 50` is refused. A stale edit shows the latest values so you can make your change again. An expense may take you below zero, with a warning. Transactions created by bills, shared expenses, or settlements cannot be edited directly.
- **Dashboard:** your recorded balance, the next allowance date, and a reminder until this cycle's allowance is recorded. Float never assumes the allowance arrived.
- **Audit trail:** every financial change is recorded in an append-only log.

**Day 2 (2 October), bills, goals, safe-to-spend, and the forecast:**
- **Bills:** add a bill that repeats weekly or monthly (every 1–52 weeks or 1–12 months), or happens once, ending on a date or after a number of times. Float generates each bill when a page needs it, never twice. Each bill shows as upcoming, reserved, overdue, paid, or skipped, in words. Paying creates the expense in your transactions; undoing removes it again. You can skip a bill, change one bill's amount or due date, change "this and future" bills (earlier ones keep their amounts), or end a bill (overdue ones stay until paid or skipped).
- **Goals:** protect money for a goal and release it again. Protected money stays in your balance but is never counted as safe to spend, and no transaction is created. With a target date, Float works out how much to set aside this cycle and shows whether you are on plan, behind, overdue, or complete. Goals marked "reserve automatically" set that amount aside in safe-to-spend.
- **Safe to spend:** the dashboard shows how much you can spend per day until your next allowance. It subtracts bills due before then, protected savings, and planned goal contributions from your recorded balance, and every step links to the records behind it. A shortfall is shown in words. "Can I afford it?" previews a purchase without saving anything.
- **Forecast:** your spending pace over the last 28 days (or "not enough history" under 7 days), how many days your money lasts at that pace, what would be left at the next allowance, a day-by-day chart with and without the allowance, its lowest point, and an estimate for the next cycle.
- **Budgets:** set a limit per category for every cycle or for this cycle only. Each category shows what you spent and whether it is OK, at 80% or more, or over (and by how much).
- **Unusual expenses:** an expense far above what you usually spend in that category (compared with your last 90 days, once there are 8 earlier expenses) is flagged in the list, with the reason.

Household shares and payables appear as €0.00 until households arrive on 3 October, with splitting and settlements (see `planned-commits.md`).

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
pytest --cov=app.identity --cov=app.ledger --cov=app.planning --cov=app.insights --cov=app.application --cov=app.shared --cov-report=term-missing
```

The second command is the NFR-08 coverage set, limited to the modules that exist so far. `app.insights` joined it on 2 October; `app.households` joins it when it is built.

| Date | Tests | Coverage of the NFR-08 modules | Coverage of all modules |
|---|---|---|---|
| 30 Sep | 113 passed | 100% of `app.shared` | 99% (342 statements, 2 missed) |
| 1 Oct | 249 passed | 99% (763 statements, 10 missed) | 97% (1,333 statements, 40 missed) |
| 1 Oct, after the review fixes | 285 passed | 99% (800 statements, 9 missed) | 97% (1,418 statements, 42 missed) |
| 2 Oct | 423 passed | 99% (1,546 statements, 20 missed; now including `app.insights`) | 97% (2,463 statements, 64 missed) |

These figures were measured on macOS with Python 3.14.7. The suite includes Hypothesis property tests, an architecture test that enforces the domain boundaries, and an authorization test for every page that shows records.

Each day, deliberate bugs were injected into the new code to check that the tests catch them:
- **30 September:** five mutations, all caught after one test was added.
- **1 October:** 30 mutations across identity, the web layer, the ledger, and setup. The first run missed five (the dummy-password path, two redirect checks, clearing the logout cookie, and showing every form problem at once). Tests were added and all 30 are now caught.
- **1 October, real server:** the final smoke test also found that the request log never reached the server output. That was fixed, with a test, before release.
- **1 October, review:** a helper agent (Claude Opus 5.5) reviewed all of Days 0–1. It found no critical or high-severity problems and 11 smaller ones, all fixed the same day with 36 new tests. Fifteen mutation checks confirm the new tests guard the fixes:
  - `12 50` was read as €1,250;
  - setting up on payday caused a reminder that could double-count the allowance;
  - there was no below-zero warning;
  - a lock could end early;
  - huge numbers caused 500 errors;
  - error pages showed you as signed out;
  - form posts without an Origin header were allowed;
  - the 64 KB form limit was missing;
  - stale edits lost your input;
  - plus two smaller integrity gaps.
- **2 October:** 59 mutations across bills, goals, safe-to-spend, the forecast, goal plans, budgets, and unusual expenses. The first runs missed 19. Sixteen were real gaps and got tests: exact boundaries (a bill due today when a series ends, a runway equal to the days left, a bill due on payday, ties for the lowest point, the 90-day lookback), skipped bills surviving an ended series, which budget scope is saved, and two update paths that did not check their row count. The other three cannot change behaviour: the conditional SQL updates re-check what the Python checks first. All Fixture A, B, C, E, and F values from SRS §4.10 that need no household are reproduced exactly.
- **2 October, real server:** a 13-step smoke test on `python app.py` covered registering, setting up, adding and paying a bill, adding a goal, the dashboard and preview, the forecast, and budgets. Every step passed, with one request-log line per request and no server errors. The dashboard, bills, and forecast pages were also checked in a browser.

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

Commits exist for 28 and 30 September. Nothing was pushed on 29 September, so reaching six days needs meaningful pushed work on every remaining date: 1, 2, 3, and 4 October. Features are built from 1 to 3 October. 4 October is reserved for testing, bug fixes, and UI polish, and its fixes are still real pushed commits. Add truthful AI log entries and decisions as the work happens, not retrospectively.
