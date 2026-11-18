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

## Assignment 2: two services (in progress)

Float is being split into two services, each with its own SQL Server database, a static web UI, and a pipeline that deploys to Azure. The full plan, day by day, is in `plan.md`; the decisions are ADR 6 to 10 in `ADR.md`.

- **personal** (`services/personal`): accounts and sign-in, the ledger, bills, goals, budgets, safe-to-spend, the forecast and alerts.
- **households** (`services/households`): households, members, invitations, shared expenses, balances, settlements and household bills.

They talk over HTTP. When a flatmate records a shared expense, the households service asks the personal service to add the payer's ledger row (`POST /internal/transactions`). When the dashboard needs your household terms, the personal service asks the households service (`GET /internal/users/{id}/position`). Every call has a 2-second timeout. If one service is down, the other keeps serving its own data and answers the cross-service actions with a clear "unavailable, nothing was saved" (503) instead of an error page.

The server-rendered pages of Assignment 1 are gone: both services now serve JSON only, and the browser UI is being rebuilt as static files in `ui/`.

## How to run it

You need Docker Desktop. On Apple Silicon, turn on "Use Rosetta for x86/amd64 emulation" in Docker Desktop's settings, because SQL Server has no arm64 image.

```bash
git clone https://github.com/Sanad-AlBilleh/Float.git
```

```bash
cd Float
```

```bash
cp .env.example .env
```

Replace every value in `.env` with your own (passwords: at least 8 characters with upper case, lower case and digits, and no `@ : / ? #`). Then:

```bash
docker compose up --build
```

The first start downloads SQL Server and takes a minute or two. Compose then:

1. starts SQL Server (`db`) and waits until it answers;
2. runs `db/init.sql` once (`db-init`), which creates the `personal` and `households` databases and one login per service, each allowed into its own database only;
3. starts both services. Each applies its own migrations on startup and logs `migration applied: 001_init.sql` (or `migrations: nothing to apply` on later starts).

Check them: http://localhost:8001/health and http://localhost:8002/health answer `{"status": "ok", "db": "ok", "version": "local"}`. The API documentation is at http://localhost:8001/api/docs and http://localhost:8002/api/docs.

Your data stays in the `mssql-data` volume between runs. `docker compose down -v` deletes it.

### Running one service on its own

Start only the database with `docker compose up -d db db-init`, then, in `services/personal` (or `services/households`):

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
DATABASE_URL="mssql://personal_svc:<PERSONAL_DB_PASSWORD>@localhost:1433/personal" TOKEN_SECRET=dev INTERNAL_API_KEY=dev uvicorn app.main:app --port 8001
```

Without the other service running, the cross-service parts answer "unavailable" and everything else works.

## Configuration

Each service reads only environment variables (Assignment 2 §7.7). Secrets have no default and the service refuses to start without them.

| Variable | Service | Default | Meaning |
|---|---|---|---|
| `DATABASE_URL` | both | secret | `mssql://user:password@host:1433/database`, plus `?encrypt=require` on Azure |
| `TOKEN_SECRET` | both | secret | personal signs sign-in tokens with it; households checks them |
| `INTERNAL_API_KEY` | both | secret | sent on `/internal` calls between the services |
| `PORT` | both | `8000` | port inside the container |
| `CORS_ORIGINS` | both | `http://localhost:8080` | the UI's origin, the only one allowed to call the API from a browser |
| `HOUSEHOLDS_URL` / `PERSONAL_URL` | personal / households | `http://households:8000` / `http://personal:8000` | where the other service is |
| `HOUSEHOLDS_TIMEOUT_S` / `PERSONAL_TIMEOUT_S` | personal / households | `2` | timeout for every call to the other service |
| `GIT_SHA` | both | `dev` | reported by `/health`; set at build time |
| `APP_TIMEZONE` | both | `Europe/Madrid` | the time zone for "today" |
| `DB_CONNECT_RETRIES` | both | `8` | connection retries at startup while a paused Azure database resumes |
| `SESSION_IDLE_HOURS`, `SESSION_MAX_DAYS` | personal | `48`, `14` | session lifetimes |

## Tests and coverage

Tests run against a real SQL Server database, never against Azure. Start the local one first (`docker compose up -d db db-init`); the tests create `personal_test` and `households_test` on it, using the SA password from `.env` (or set `TEST_DATABASE_URL`). In each service folder:

```bash
pip install -r requirements-dev.txt
```

```bash
ruff check app tests
```

```bash
pytest --cov --cov-report=term
```

Each service tests its own code, with the other service replaced by an in-memory stand-in (`tests/fakes.py`): a scripted households service in the personal tests, and a small fake ledger in the households tests. The real calls between them are tested together in the cross-service integration test (coming with the CI workflow).

## Project structure

```
docker-compose.yml          the whole system: SQL Server, db-init and the two services
db/init.sql                 creates one database and one login per service (local only)
services/personal/          Identity, Ledger, Planning and Insights
  app/api/                  routes, /internal, /health, auth, errors, request logs
  app/clients/households.py the HTTP client for the households service
  app/db/                   SQL Server connection with retries, transactions, migration runner
  migrations/               001_init.sql ...
  Dockerfile, requirements.txt, requirements-dev.txt, pyproject.toml
services/households/        Households, shared expenses, settlements, household bills
  app/clients/personal.py   the HTTP client for the personal service
  (same layout as personal)
plan.md                     the Assignment 2 plan and daily schedule
```

Inside each service, the domain packages still only expose their `api.py` and never import each other, and an architecture test now also checks that no service contains the other's code or queries the other's tables.

## Not built

- CSV import and the end-of-cycle review (stretch features I never planned to finish).
- "This and future" edits for household bills. You can edit or skip one occurrence, or end the bill and create a new one.
- Background jobs, emails and push notifications. Alerts show up when you open the app (see ADR 5).
- The A1 demo-data script and speed check worked on the SQLite monolith only and were removed in Assignment 2 (they are in the Git history).

## Documents

- `ADR.md`: my architecture decisions (1 to 5 from Assignment 1, 6 to 10 from Assignment 2).
- `plan.md`: the Assignment 2 plan.
- `AI_USAGE.md`: how I used AI tools, prompt by prompt.
- `docs/report.md`: the project report with the architecture and database diagrams.
- `PRD.md` and `SRS.md`: the product and software requirements.
- `EXECUTION_PLAN.md` and `planned-commits.md`: the day-by-day build plan.
- `docs/acceptance-2026-10-04.md`: the final checks on 4 October.

## Commit history

The project was built in daily slices between 28 September and 4 October 2026, with one pull request merged per day. 63 commits were pushed on 6 different days (3, 9, 11, 8, 9 and 23), and the biggest day, 4 October, holds 37% of them, under the 40% limit.
