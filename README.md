# Float

Float is a money app for students who live on a monthly allowance and share a flat. It answers one question: **how much can I safely spend today?**

To get that number it takes your recorded balance and subtracts your bills due before the next allowance, your share of the flat's bills, what you owe your flatmates, and the money you set aside for savings goals. Then it divides what is left by the days until your next allowance.

Everything is entered by hand. Float never connects to a bank, and the only currency is the euro.

## Features

**Personal money**
- Accounts with login, logout, password change and lockout after 5 failed logins.
- Setup: start date, current balance, allowance day, planned allowance (default €750) and how much you want to save each month.
- Income and expenses. Type what you bought ("Pizza with friends") and Float picks the category for you. You can also add your own categories.
- Recurring bills (weekly, monthly or one-off). Pay, undo, skip, edit one, or edit "this and future".
- Savings goals with a monthly plan that tells you how much to set aside each cycle.
- Budgets per category, with warnings at 80% and when you go over.
- Unusual expense flags, when an expense is far above what you normally spend in that category.
- Safe-to-spend per day on the dashboard, with every step linked to the records behind it, and a "Can I afford it?" preview.
- Forecast: your spending pace, how long your money lasts, and a day-by-day chart.

**Shared living**
- Households with one-time invitation codes (valid 72 hours).
- Shared expenses split equally, by exact amounts, by percentages or by shares. The cents always add up.
- Balances and a settle-up plan ("Lucía pays Borja €12.40").
- Settlements: one person records the transfer, the other confirms it, and it is written into both people's transactions.
- Household bills like rent, where each person's share is reserved in their own safe-to-spend.

**Everything else**
- Alerts (bills due, budgets, unusual expenses, settlements waiting, and more) and an activity feed.
- A JSON API at `/api/v1` with docs at `/api/docs`.
- Works on desktop and phone (bottom tab bar on small screens).

## How to run it

You need Python 3.12 or newer. On macOS the built-in `/usr/bin/python3` is too old, so use Homebrew or python.org.

```bash
git clone https://github.com/Sanad-AlBilleh/Float.git
```

```bash
cd Float
```

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

Open http://localhost:8000, create an account and follow the setup. On Windows, activate the venv with `.venv\Scripts\activate` instead.

There is no setup wizard in the terminal and no manual migration step. On first start Float creates the database and applies the migrations by itself, and it is ready in well under a second.

## Configuration

Everything is set with environment variables. All of them are optional.

- `PORT`: the port to listen on (default `8000`). Float always binds to `0.0.0.0`.
- `DATA_DIR`: the folder for the database (default `./data`).
- `APP_TIMEZONE`: the time zone used for "today" (default `Europe/Madrid`).
- `COOKIE_SECURE`: set to `true` when served over HTTPS (default `false`).
- `SESSION_IDLE_HOURS` and `SESSION_MAX_DAYS`: session lifetimes (default 48 hours and 14 days).

A `.env` file in the project folder is read if it exists, but it is never required.

Example: `PORT=9000 DATA_DIR=/tmp/float python app.py`

## Where the data is

All data lives in one SQLite file: **`DATA_DIR/float.sqlite3`**, so `data/float.sqlite3` by default. The `data/` folder is in `.gitignore`, so every clone starts with an empty database. To back it up, copy that file while the app is stopped.

## Log in as the demo user (Borja)

To see every feature with a month of data already filled in, create the demo account **before the first start**, then start Float as normal:

```bash
python scripts/seed_demo.py data Borjita_Best_Prof "Borja Planelles" Password-is-Password
```

```bash
python app.py
```

Open http://localhost:8000 and log in with username **Borjita_Best_Prof** and password **Password-is-Password**.

The script fills `data/float.sqlite3` with a month of income, expenses, bills, goals, budgets, custom categories, alerts and a shared flat ("Piso Ruzafa"). Two flatmates joined it with invitation codes, and you can log in as them too: `lucia_demo` and `marco_demo`, with the same password. If you already started Float once, delete the `data` folder first, because the script only fills an empty database. These are made-up demo accounts with no real data.

## Tests and coverage

```bash
pytest
```

```bash
pytest --cov=app.identity --cov=app.ledger --cov=app.planning --cov=app.households --cov=app.insights --cov=app.application --cov=app.shared --cov-report=term-missing
```

The second command measures coverage of the business logic only (the five domains, the application layer and the shared rules). The web templates and routes are left out on purpose.

Result on 4 October 2026 (macOS, Python 3.14): **604 tests passed, 97% coverage of the business modules** (2,925 statements, 83 missed). Coverage of the whole app, including the web layer, is 95%.

The tests include unit tests for every worked example in the SRS, Hypothesis property tests (splits always add up, household balances always sum to zero), tests against a real SQLite file, an architecture test that stops one domain importing another, and an authorization test for every page.

`python scripts/perf_smoke.py` checks speed with 16,000 transactions: the dashboard answered in 48 ms (p95) against a 500 ms limit.

## Project structure

```
app.py                 starts the server
app/config.py          reads the environment variables
app/db/                SQLite connection, transactions and migrations (0001 to 0012)
app/identity/          accounts, sessions, login throttling
app/ledger/            transactions, categories, balance
app/planning/          bills, goals, budgets
app/households/        members, invitations, shared expenses, settlements, household bills
app/insights/          safe-to-spend, forecast, unusual expenses, alerts
app/application/       use cases that join the domains in one transaction
app/shared/            money, dates and recurrence rules (no database)
app/web/               pages, templates and CSS
app/api/v1/            JSON API
scripts/               demo data and the speed check
tests/                 the test suite
```

Each domain only exposes its `api.py`. Domains never import each other; the application layer joins them (see ADR 2).

## Not built

- CSV import and the end-of-cycle review (stretch features I never planned to finish).
- "This and future" edits for household bills. You can edit or skip one occurrence, or end the bill and create a new one.
- Background jobs, emails and push notifications. Alerts show up when you open the app (see ADR 5).

## Documents

- `ADR.md`: my five architecture decisions.
- `AI_USAGE.md`: how I used AI tools, prompt by prompt.
- `docs/report.md`: the project report with the architecture and database diagrams.
- `PRD.md` and `SRS.md`: the product and software requirements.
- `EXECUTION_PLAN.md` and `planned-commits.md`: the day-by-day build plan.
- `docs/acceptance-2026-10-04.md`: the final checks on 4 October.

## Commit history

The project was built in daily slices between 28 September and 4 October 2026, with one pull request merged per day. 63 commits were pushed on 6 different days (3, 9, 11, 8, 9 and 23), and the biggest day, 4 October, holds 37% of them, under the 40% limit.
