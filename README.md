# Float

Float is a money co-pilot for students on an allowance who share a flat. It answers one question: **what can I safely spend today, after my bills, my share of the flat's costs, what I owe my flatmates, and my savings plan?**

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

**Day 3 (3 October), households, alerts, and the API:**
- **Households:** create a household (you become its owner) and invite flatmates with a one-time code: 10 characters, valid for 72 hours, shown once. Up to eight members per household and three households per person. Owners can rename, hand over ownership, remove members, and archive. Anyone can leave once their balance is €0.00, nothing is pending, and they share no active household bill; Float lists whatever is in the way.
- **Shared expenses:** record what you paid and split it equally, by exact amounts, by percentages, or by shares. The cents always add up. The full amount goes in your transactions; only the payer can edit or delete it.
- **Balances and settling up:** each member's balance, a short settle-up plan ("Carla pays Ben €40.00") that never needs more transfers than one fewer than the people involved, though it is not always the shortest possible, and settlements. Either person records a transfer made outside Float; only the other person can confirm it, and confirming writes it into both people's transactions.
- **Household bills:** the owner sets up rent or internet with an equal, percentage, or shares split. Each person's share is set aside in their own safe-to-spend. Whoever pays turns it into a shared expense, so the others then owe their share; undo restores everything.
- **Safe to spend now includes the flat:** your share of household bills and what you owe flatmates are subtracted. What they owe you is shown but not counted until they settle. The forecast and budgets count your shares, not the cash you fronted.
- **Alerts:** bills due soon or overdue, budgets at 80% or over, a pace that will not last, unusual expenses, settlements waiting for you, new household expenses with a share for you, a missing allowance, and overdue goals. They are checked when you open the dashboard or the alert centre and after every change you save. They disappear when their reason is gone, and a dismissed alert never comes back.
- **Activity:** each household has an Activity tab in plain sentences, and the Activity page lists your own changes.
- **JSON API:** `/api/v1` offers the same features as the pages (67 operations, documented at `/api/docs`). Money is integer cents plus a display string, and errors are `application/problem+json`. Unsafe requests need the `X-CSRF-Token` header (get one from `GET /api/v1/csrf` or the login response). Money-creating posts accept an `Idempotency-Key` header.

### Not implemented

- **P2 stretch features:** CSV import, category suggestions, and the cycle review with savings sweep (FR-36–38). The plan never scheduled them.
- **"This and future" edits of household bills:** a household bill can be corrected one occurrence at a time, skipped, or ended and re-created, but not split from a date on as personal bills can. SRS §4.2 asks for this.
- **API differences from SRS §8.2:**
  - budgets use `PUT /api/v1/budgets/{category_id}` with a `scope` (every cycle, or this cycle only) instead of two separate URLs;
  - revoking an invitation and removing a member are `POST …/revoke` and `POST …/members/{id}/remove` instead of `DELETE`;
  - category consumption is part of `GET /budgets`;
  - `GET /occurrences` filters with `start` and `end`, not `from` and `to`;
  - lists return at most 200 items and have no cursor paging;
  - P2 imports are absent.
- **Idempotency:** a money-creating API call's stored response is written just after its change commits, not in the same transaction (the use cases are shared with the pages). A crash in between leaves the key reserved for 24 hours, which refuses a retry rather than duplicating money. See `app/api/v1/idempotency.py`.
- **No background jobs (ADR-5):** alerts appear when someone opens Float, not at a set time, and there are no emails or push notifications.

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
pytest --cov=app.identity --cov=app.ledger --cov=app.planning --cov=app.households --cov=app.insights --cov=app.application --cov=app.shared --cov-report=term-missing
```

The second command is the NFR-08 coverage set: every business module (the web and API layers are excluded). `app.insights` joined it on 2 October and `app.households` on 3 October.

| Date | Tests | Coverage of the NFR-08 modules | Coverage of all modules |
|---|---|---|---|
| 30 Sep | 113 passed | 100% of `app.shared` | 99% (342 statements, 2 missed) |
| 1 Oct | 249 passed | 99% (763 statements, 10 missed) | 97% (1,333 statements, 40 missed) |
| 1 Oct, after the review fixes | 285 passed | 99% (800 statements, 9 missed) | 97% (1,418 statements, 42 missed) |
| 2 Oct | 423 passed | 99% (1,546 statements, 20 missed; now including `app.insights`) | 97% (2,463 statements, 64 missed) |
| 3 Oct | 562 passed | 97% (2,836 statements, 84 missed; now including `app.households`) | 95% (4,625 statements, 250 missed) |

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
- **3 October:** 62 mutations across households, splits, balances, settlements, household bills, alerts, and the API idempotency layer. The first runs missed 19. Thirteen were real gaps and now have tests:
  - an archived household's code still working;
  - a plain member removing someone;
  - former members making changes, or seeing later history;
  - archiving while someone owes money;
  - a household bill due on payday;
  - an exact split template that adds up;
  - non-participants paying a bill;
  - shares missing from budgets;
  - an alert not reopening;
  - alerts not refreshed straight after a post;
  - a concurrent duplicate idempotent request.

  The other six cannot change behaviour, because a SQL condition repeats the Python check. The full SRS Fixture A now passes end to end: €308.00, €28.00/day, every forecast value, and all four conservation steps. A Hypothesis property checks the conservation rule over random sequences of actions.
- **3 October, real server:** a 23-step smoke test on `python app.py` with two flatmates covered setup, a household, an invitation, a shared expense, the settle-up plan, a household bill, a confirmed settlement, the dashboard, forecast, alerts, activity, and the JSON API. Every step passed, with one request-log line per request and no server errors. The browser check found one real bug: checkboxes and radio buttons were stretched like text boxes, which squeezed their labels. It was fixed the same day.
- **2 October, real server:** a 13-step smoke test on `python app.py` covered registering, setting up, adding and paying a bill, adding a goal, the dashboard and preview, the forecast, and budgets. Every step passed, with one request-log line per request and no server errors. The dashboard, bills, and forecast pages were also checked in a browser.

## Documentation

- `PRD.md`: user problem, v0.1 → v0.2 changes, product principles, scope and priorities (P0/P1/P2), and success criteria.
- `SRS.md`: functional requirements, exact calculation rules with worked fixtures, state machines, architecture, schema, security, and acceptance tests.
- `AI_USAGE.md`: meaningful AI interactions and the boundary between AI drafts and the student's own explanations.
- `EXECUTION_PLAN.md`: the task-by-task implementation plan for every day, with interfaces, SQL, tests, and traceability.
- `planned-commits.md`: the daily commit schedule and the rules that keep the history honest.
- `ADR.md`: the five architecture decisions, written on 1, 2, and 3 October: stack, domain boundaries, schema, testing strategy, and the deliberate omission of a background scheduler.
- `docs/report.md`: the draft report (4–5 pages). Its measured numbers are refreshed on 4 October.

The final submission also needs a 4–5-page report and the written comprehension check.

## Assignment timeline

Deadline: **4 October 2026, 23:59**, in the course's deadline timezone.

The assignment requires at least 12 meaningful commits across at least six calendar days, pushed to GitHub on those days. No single day may contain more than 40% of the final commit total. Never fabricate or backdate commits.

Commits exist for 28 and 30 September. Nothing was pushed on 29 September, so reaching six days needs meaningful pushed work on every remaining date: 1, 2, 3, and 4 October. Features are built from 1 to 3 October. 4 October is reserved for testing, bug fixes, and UI polish, and its fixes are still real pushed commits. Add truthful AI log entries and decisions as the work happens, not retrospectively.
