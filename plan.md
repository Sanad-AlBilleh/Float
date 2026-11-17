# Assignment 2 plan: split, ship and operate Float

This is the plan for turning the Assignment 1 monolith into two services, a static UI, a CI/CD pipeline and a serverless Azure deployment. It is written on 17 November 2026, before any Assignment 2 code. The same rules as `planned-commits.md` apply: each commit contains work done that day, nothing is backdated, every day ends with a branch pushed, a pull request opened and merged into `main`, and this file is updated if the plan changes.

- **Repository:** the same one as Assignment 1, `Sanad-AlBilleh/Float`. Changes reach `main` only through pull requests.
- **Student:** `sgealbilleh.ieu2024`. **Prefix:** `sgealbilleh-ieu2024`. **UI storage account:** `sgealbillehieu2024ui`.
- **Deadline for a working deployment:** Saturday 21 November. Sunday 22 November is kept for fixes after my own review, the report, and the `submission` tag.

---

## 1. Decisions (become ADR-6 to ADR-10)

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Where the seam is | **`personal`** (Identity, Ledger, Planning, Insights) and **`households`** (households, members, invitations, shared expenses, household bills, settlements) | ADR-2 already names Households as the package to cut out. Planning keeps its foreign key to `transactions` because both stay in `personal`. |
| D2 | Authentication across the seam | `personal` owns users and issues **signed access tokens** (HMAC-SHA256 with the standard library, `TOKEN_SECRET`). `households` checks the signature and expiry **locally**. The browser sends `Authorization: Bearer <token>`. | `households` keeps serving its own domain when `personal` is down (§3 partial failure). No cookies across origins, so no CSRF code is needed. |
| D3 | Service-to-service calls | Plain HTTP with `httpx`, base URL from `PERSONAL_URL` / `HOUSEHOLDS_URL`, a timeout on every call (`*_TIMEOUT_S`, default 2 s), and an `X-Internal-Key` header (`INTERNAL_API_KEY` secret) on `/internal/*` endpoints | §1a: HTTP only, URLs from environment variables, every outbound call has a timeout. |
| D4 | Cross-seam flows (server side) | (a) **Recording a shared expense** (`households` → `POST personal /internal/transactions`), the required server-side write. (b) **Confirming a settlement** (`households` → `personal`, two ledger transactions). (c) **Member names** (`households` → `GET personal /internal/users?ids=`). (d) **Dashboard household balance and household alerts** (`personal` → `GET households /internal/users/{id}/summary`). | These were cross-package joins or one-transaction writes in A1. They become calls now. |
| D5 | When the other service is down | **Reads degrade, writes fail clearly.** Member names fall back to the cached `member_name` column (migration 002), then to "Member #id". The dashboard shows "Household balances unavailable". Writes that need a ledger transaction answer `503 {"detail": "Your ledger is unavailable, nothing was saved. Try again."}`, and nothing is half-saved. | Money must not be written half on one side. Reading stale names is harmless. |
| D6 | Consistency of cross-seam writes | `households` first calls `personal` with an **idempotency key** (`household-expense:<uuid>`), then stores the returned `transaction_id` as a plain ID. If its own insert then fails, it calls `DELETE /internal/transactions/{id}` (compensation). A retry with the same key never creates two transactions. | No distributed transaction or message broker (out of scope §1c). This replaces the A1 single-transaction guarantee (ADR-2) and is the "integrity lost at the seam" in ADR-7. |
| D7 | Migrations | **Our own runner** (already in A1) with numbered T-SQL files per service and a `schema_migrations` table. The SQL Server history starts fresh: `001_init.sql` per service is the A1 final schema ported to T-SQL. | No new dependency. I can explain every line. |
| D8 | Driver | `pymssql` (wheels include FreeTDS, so no ODBC driver in the image). `DATABASE_URL=mssql://user:password@host:1433/db` parsed by our code. | Small image, no system packages. |
| D9 | UI | **Vanilla HTML/CSS/JS, no build step**, in `ui/`. `ui/config.js` is generated at deploy time. A **trimmed UI** covers the core flows of both domains (see §6). | Static files go straight to `$web`. No framework to explain. |
| D10 | Infrastructure | **Azure CLI**: commands for the one-time setup in the README, `az` in the CD workflow | Small system, and every command is visible. IaC is left for ADR-10 discussion. |
| D11 | Registry | GHCR (free), images public, built with `provenance: false` | §1b default, no fixed cost. |
| D12 | Not built (ADR-10) | A **gateway / backend-for-frontend container** that would hide two origins from the browser and keep the token server-side | §1c forbids a third container. ADR-10 explains when it would be worth it. |

---

## 2. Target repository layout

```
Float/
├── services/
│   ├── personal/
│   │   ├── app/                 # identity, ledger, planning, insights, shared, application, api, db
│   │   ├── migrations/          # 001_init.sql, 002_...sql (T-SQL)
│   │   ├── tests/               # unit + DB tests for this service
│   │   ├── scripts/             # export_openapi.py, seed (idempotent)
│   │   ├── Dockerfile
│   │   ├── .dockerignore
│   │   ├── requirements.txt     # pinned, ≤ 12 third-party packages
│   │   ├── pyproject.toml       # ruff + pytest + coverage settings
│   │   └── openapi.yaml         # generated, committed
│   └── households/              # same shape
├── ui/                          # static site (index.html, pages, css, js, config.js template)
├── db/init.sql                  # idempotent: databases, logins, users, roles (local only)
├── tests/integration/           # cross-seam tests against the compose stack
├── .github/workflows/ci.yml     # push (not main) + PR + workflow_call
├── .github/workflows/cd.yml     # push to main: ci → build/push → deploy → UI → health
├── docker-compose.yml
├── .env.example                 # placeholder values only, .env is gitignored
├── system.yaml
├── system.schema.json           # copied from Blackboard
├── ADR.md  AI_USAGE.md  README.md  plan.md
└── docs/   (A1 docs stay; A2 evidence screenshots/logs go in docs/a2/)
```

---

## 3. What is removed

| Remove | Why |
|---|---|
| `app.py` (root launcher) and the root `requirements.txt` | Each service has its own entry point and manifest (§1a replaces the A1 single-manifest rule). |
| `app/web/` (all 61 page routes: `routes.py`, `auth.py`, `forms.py`, `rendering.py`, `templating.py`, `charts.py`, `security.py`, `deps.py` cookie/CSRF parts, `middleware.py` page parts, …) | Server-rendered pages become a static UI (§2 of the assignment). Services keep only JSON APIs. |
| `app/templates/` (37 Jinja templates) and the template part of `app/static/` | Same. The CSS moves to `ui/css/`. |
| Dependencies `jinja2` and `python-multipart` | No templates, no form posts. |
| Cookie sessions, `ANON_CSRF_COOKIE`, `verify_csrf`, `same_origin`, `safe_next`, `GET /api/v1/csrf` | Bearer tokens in a header cannot be sent by another site, so CSRF protection is no longer needed (D2). |
| `app/db/connection.py` SQLite pragmas, `BEGIN IMMEDIATE` unit of work, `data/float.sqlite3` | Replaced by a SQL Server connection with retry and normal transactions. |
| SQLite migration files `0001`–`0012` | Ported into one `001_init.sql` per service (D7). Kept in Git history. |
| `tests/web/*` page tests | Pages are gone. The money and permission checks they made are re-done as API tests (§8). |
| `tests/test_architecture.py` import rule across 5 packages | Replaced by a rule per service: no service imports the other's code, and no code reads the other service's database. |

Nothing in `PRD.md`, `SRS.md`, `EXECUTION_PLAN.md`, `planned-commits.md` or `docs/` is deleted. They are the A1 record.

---

## 4. Service `personal` (Identity, Ledger, Planning, Insights)

### 4.1 Code that moves in unchanged (logic) or with small edits

- `app/identity/` (users, password hashing with `hashlib.scrypt`, login attempts). **Edit:** sessions become signed tokens (`app/identity/tokens.py`: `issue(user_id, ttl)` / `verify(token)` with `hmac.compare_digest`). The `sessions` table stays for logout revocation inside `personal`.
- `app/ledger/`, `app/planning/`, `app/insights/` (pure functions unchanged: money, cycles, safe-to-spend, forecast, anomaly, consumption).
- `app/shared/` (money, dates, recurrence, clock, errors): **copied** into both services. ADR-6 explains why it is copied and not shared as a library.
- `app/application/`: `accounts`, `bills`, `budgets`, `categories`, `goals`, `setup`, `transactions`, `audit`, `context`, `activity`.
  - **Edit `dashboard.py` and `alerts.py`:** remove `from app.households` imports. Household numbers come from `clients/households.py` (`GET /internal/users/{id}/summary`). On timeout, connection error or 5xx it returns `None`, and the response carries `"households": {"available": false}`.
  - **Edit `bills.py`/`shared_money` parts** that belonged to Households: they move to the households service.
- `app/api/v1/routes.py`: keep `/auth/*`, `/me`, `/setup`, `/settings`, `/transactions*`, `/bills*`, `/occurrences*`, `/goals*`, `/budgets*`, `/dashboard*`, `/forecast`, `/alerts*`, `/activity`. Remove `/households*`, `/household-occurrences*`, `/csrf`.

### 4.2 New in `personal`

- `app/clients/households.py`: `httpx.Client(base_url=HOUSEHOLDS_URL, timeout=HOUSEHOLDS_TIMEOUT_S)`.
- `app/api/internal.py` (requires `X-Internal-Key`):
  - `GET /internal/users?ids=1,2,3` → `[{id, display_name}]`
  - `GET /internal/users/{id}/cycle` → the user's current allowance cycle (households needs it for "due this cycle")
  - `POST /internal/transactions` (with `Idempotency-Key`) → creates an expense/income in a user's ledger and returns `{id}`
  - `DELETE /internal/transactions/{id}` → compensation for D6
- `app/health.py`: `GET /health` (see §7.3).
- `app/logging_mw.py`: one stdout line per request (§7.4).
- `app/db/` rewritten for SQL Server (§5).
- CORS: `CORSMiddleware(allow_origins=CORS_ORIGINS.split(","), allow_methods=*, allow_headers=["Content-Type","Authorization","Idempotency-Key"])`.

### 4.3 Tables owned by `personal`

`users`, `sessions`, `login_attempts`, `categories`, `ledger_settings`, `transactions`, `planning_settings`, `bill_series`, `bill_occurrences`, `savings_goals`, `goal_movements`, `budget_templates`, `category_budgets`, `alerts`, `alert_cursors`, `audit_events`, `idempotency_keys`, `health_probe` (new), `schema_migrations`.

**New column:** `transactions.source NVARCHAR(20) NOT NULL DEFAULT 'manual'` (`'manual'`, `'household_expense'`, `'settlement'`) plus `source_ref NVARCHAR(64) NULL`. These replace the A1 foreign key from `shared_expenses.payer_transaction_id`. A household-created transaction can only be edited or deleted through `households`.

### 4.4 Environment variables (`personal`)

`PORT` (8000), `DATABASE_URL` (secret), `TOKEN_SECRET` (secret), `INTERNAL_API_KEY` (secret), `HOUSEHOLDS_URL` (`http://households:8000`), `HOUSEHOLDS_TIMEOUT_S` (2), `CORS_ORIGINS` (`http://localhost:8080`), `TOKEN_TTL_MIN` (720), `GIT_SHA` (`dev`), `DB_CONNECT_RETRIES` (8).

---

## 5. Service `households`

### 5.1 Code

- `app/households/` (rules, allocation/splits, balances, settlements, bills): pure logic unchanged.
- `app/application/households.py`, `shared_money.py`, `authz.py` move here. **Edit:**
  - `record_expense`: (1) validate, (2) `POST personal /internal/transactions` with `Idempotency-Key`, (3) insert `shared_expenses` with `payer_transaction_id` as a plain INT, (4) on failure in (3) call `DELETE` (compensation). If (2) fails → 503 with a clear message, nothing saved.
  - `edit_expense` / `delete_expense`: same pattern (PATCH/DELETE on `personal`).
  - `confirm_settlement`: two `POST /internal/transactions` (payer expense, payee income), each with its own idempotency key, then mark the settlement confirmed.
  - `_check_paid_on` / `_viewer_cycle`: read the user's cycle via `GET /internal/users/{id}/cycle`. If unavailable, use the calendar month and flag `"cycle_estimated": true`.
  - Member names: `GET /internal/users?ids=…`. On success refresh `memberships.member_name`. On failure use the cached column.
  - `_category_ids`: categories belong to `personal`. Household expenses keep `category_id` as a plain INT, validated through the transaction call (personal rejects an unknown category). The FK is deliberately not enforced locally (ADR-7).
- Auth: `app/auth.py` verifies the bearer token with `TOKEN_SECRET` (copy of `tokens.verify`, no DB call).
- `app/api/routes.py`: `/households*`, `/household-occurrences/*` from the A1 router, plus `GET /internal/users/{id}/summary` (net balance across households and pending settlements/bills for the dashboard and alerts).
- `/health`, logging, CORS, `clients/personal.py`: same as `personal`.

### 5.2 Tables owned by `households`

`households`, `memberships`, `invitations`, `shared_expenses`, `shared_expense_splits`, `household_bill_series`, `household_bill_participants`, `household_bill_occurrences`, `settlements`, `audit_events` (own copy), `idempotency_keys` (own copy), `health_probe`, `schema_migrations`.

All `REFERENCES users (id)` (16 in households) and `REFERENCES transactions (id)` become **plain `INT NOT NULL` columns** with an index. Foreign keys inside the households tables stay.

### 5.3 Environment variables (`households`)

`PORT`, `DATABASE_URL` (secret), `TOKEN_SECRET` (secret), `INTERNAL_API_KEY` (secret), `PERSONAL_URL` (`http://personal:8000`), `PERSONAL_TIMEOUT_S` (2), `CORS_ORIGINS`, `GIT_SHA`, `DB_CONNECT_RETRIES`.

---

## 6. Static UI (`ui/`)

Vanilla JS, served by `nginx:alpine` locally and by the storage static website on Azure.

```
ui/
├── index.html            # login / register
├── setup.html            # first-time allowance setup
├── dashboard.html        # safe-to-spend, cycle, upcoming bills, alerts, household balance box
├── transactions.html     # list + add/edit/delete
├── bills.html            # bill series, pay an occurrence
├── goals.html            # goals + movements
├── budgets.html          # category budgets
├── households.html       # list, create, join by code
├── household.html        # ?id= : members, expenses, balances, settlements, household bills
├── css/float.css         # moved from the A1 static CSS
├── js/api.js             # fetch wrapper (below)
├── js/auth.js            # token in localStorage, redirect to index.html when 401
├── js/pages/*.js         # one script per page
└── config.js             # local default; overwritten by CD
```

- **`config.js`:** `window.FLOAT_CONFIG = { personalUrl: "http://localhost:8001", householdsUrl: "http://localhost:8002" };` CD writes the Azure URLs.
- **`api.js`:** every call has an `AbortController` timeout (15 s). On `503`, a network error or a timeout it shows a banner, *"Float is starting up (the database may be waking). Retrying…"*, retries 3 times with backoff (5 s, 10 s, 20 s), then shows *"Still starting, try again in a minute"* with a Retry button. Errors from the API (`detail`) are shown next to the form. It never shows a blank page.
- **Degraded states:** dashboard "Household balances unavailable", household page "Ledger unavailable: expenses can be viewed but not added", member names from the cache.
- **Trimmed (API kept, no page):** activity feed, forecast chart page, custom categories management, account/password page, separate alerts page (alerts show on the dashboard). Listed in the README as a known limitation.

---

## 7. Database, migrations, health, logs

### 7.1 SQLite → SQL Server port rules (applied to every SQL file and every query)

| SQLite (A1) | SQL Server (A2) |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `INT IDENTITY(1,1) PRIMARY KEY` |
| `TEXT` | `NVARCHAR(n)` (`NVARCHAR(MAX)` only for notes) |
| dates stored as ISO `TEXT` | `DATE` / `DATETIME2` |
| booleans `INTEGER 0/1` | `BIT` |
| `STRICT` tables | removed (SQL Server is typed already) |
| `UNIQUE` on a nullable column (e.g. `paid_transaction_id`) | **filtered unique index** `WHERE col IS NOT NULL` (SQL Server allows only one NULL in a UNIQUE constraint) |
| `INSERT … ON CONFLICT DO NOTHING` (`ensure_materialized`) | `INSERT … SELECT … WHERE NOT EXISTS (…)` inside the transaction, plus catching error 2627/2601 |
| `INSERT … RETURNING id` / `lastrowid` | `INSERT … OUTPUT INSERTED.id VALUES …` |
| `LIMIT n OFFSET m` | `ORDER BY … OFFSET m ROWS FETCH NEXT n ROWS ONLY` / `TOP (n)` |
| `?` placeholders | `%s` (pymssql) |
| triggers that block UPDATE/DELETE on `goal_movements`, `audit_events` | `CREATE TRIGGER … INSTEAD OF UPDATE, DELETE AS THROW 50001, 'immutable', 1;` |
| `CHECK` rules (amounts ≤ €1,000,000 in cents) | same `CHECK` constraints |
| `BEGIN IMMEDIATE` | `conn.autocommit(False)`, explicit commit/rollback. Optimistic `version` columns stay. |

### 7.2 Migrations

- `services/<svc>/migrations/001_init.sql`: the full A1 schema for that service's tables, ported, plus `health_probe` and seed rows for the fixed categories (`personal`).
- Runner (`app/db/migrations.py`, reused from A1): creates `schema_migrations(version NVARCHAR(50) PK, applied_at DATETIME2)` if missing, applies missing files in order, **each file in one transaction together with its `schema_migrations` row**, and logs `migration applied: 002_member_name.sql` or `migrations: nothing to apply`. Startup runs it once. Max replicas = 1, so it never runs twice at the same time. Files are split on `GO` lines.
- **The data-changing migration (§4.3 of the assignment):** `households/migrations/002_member_name.sql`:
  `ALTER TABLE memberships ADD member_name NVARCHAR(80) NULL; GO UPDATE memberships SET member_name = CONCAT('Member #', user_id) WHERE member_name IS NULL;`
  Rows already in the table keep everything and get a backfilled value. The service then refreshes it from `personal` when it can. It is the cache behind D5, so it is not a new feature.
  A second one in `personal`: `002_transaction_source.sql` adds `source`/`source_ref` with default `'manual'` (backfills existing transactions).
  **Order on Azure:** deploy with only `001` → create data through the UI → deploy the `002` files → screenshot the data before and after plus the startup log line (evidence for the report).
- Seeding: an idempotent demo seed per service (`INSERT … WHERE NOT EXISTS`), run only when `SEED_DEMO=true` (locally yes, Azure no).
- No code drops tables or recreates databases. Compose uses a named volume, which is never deleted to redeploy.

### 7.3 `GET /health`

Within a 3 s budget: `UPDATE health_probe SET checked_at = SYSUTCDATETIME() WHERE id = 1; SELECT checked_at …` in a transaction.
→ `200 {"status":"ok","db":"ok","version":"<GIT_SHA>"}` or `503 {"status":"error","db":"<reason>","version":…}`. It never calls the other service.

### 7.4 Logs and connection retry

- Middleware: `{"method":"GET","path":"/transactions","status":200,"duration_ms":12.4}` (JSON, stdout, one line per request).
- `connect()` retries on errors 40613, 20002, 20003 and connection timeouts with exponential backoff (1, 2, 4, 8, 16, 30 s…) up to `DB_CONNECT_RETRIES`. Startup migration waits up to about 90 s for a paused Azure database.

---

## 8. Tests

| Kind | Where | What |
|---|---|---|
| Pure unit tests | `services/*/tests/` | A1 tests for money, cycles, recurrence, rules, splits, balances, forecast, Hypothesis properties. They move with their package, unchanged. |
| DB/API tests | `services/*/tests/api/` | FastAPI `TestClient` against a real SQL Server test database (`TEST_DATABASE_URL`). Replace the most valuable `tests/web/*` checks (permissions, money totals, bill pay/undo). |
| Client tests (with a stub) | `services/*/tests/test_clients.py` | `httpx.MockTransport`: timeout → degraded result, 5xx → 503 with message, idempotency key sent, compensation DELETE called. |
| Health/logging tests | both | 200 with DB, 503 with a broken `DATABASE_URL`, one log line per request. |
| Migration tests | both | Applying twice applies nothing. `002` keeps existing rows and backfills. |
| **Cross-seam integration** | `tests/integration/test_seam.py` | Against the **compose stack**: register on `personal`, create a household, record a shared expense on `households`, check the transaction exists in `personal`. Then `docker compose stop personal`: `households` still lists households (names from cache), adding an expense returns 503 with the designed message, and nothing hangs (< 5 s). ADR-9 justifies compose over a stub. |
| Coverage | CI | `pytest --cov=app --cov-fail-under=70` per service. Core logic = domain packages + application. API wiring and `main.py` are omitted in `pyproject.toml` and the omission is explained in ADR-9. |
| Lint | CI | `ruff check` per service. |

---

## 9. Containers and compose

### 9.1 Dockerfile (same shape for both services)

```dockerfile
FROM python:3.13-slim            # exact tag pinned; 3.13 because pymssql ships wheels for it
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY migrations/ ./migrations/
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA PORT=8000
RUN useradd --uid 10001 --no-create-home float
USER float
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

No `COPY . .`, no `.env` (`.dockerignore` excludes `.env`, `tests/`, `.venv/`), pinned requirements, non-root user. The A1 code currently runs on Python 3.14. Day 2 checks that it runs on 3.13 (or uses 3.14 if pymssql wheels exist).

### 9.2 `docker-compose.yml`

| Service | Image | Notes |
|---|---|---|
| `db` | `mcr.microsoft.com/mssql/server:2022-latest` | `ACCEPT_EULA=Y`, `MSSQL_SA_PASSWORD=${MSSQL_SA_PASSWORD:?}` from `.env`, named volume `mssql-data`, healthcheck with `sqlcmd -C -Q "SELECT 1"`, `platform: linux/amd64` (Rosetta on Apple Silicon) |
| `db-init` | same image | Runs `db/init.sql` with `sqlcmd -v PERSONAL_DB_PASSWORD=… HOUSEHOLDS_DB_PASSWORD=…`, `depends_on: db: service_healthy`, `restart: "no"` |
| `personal` | `build: ./services/personal` | port `8001:8000`, `depends_on: db-init: service_completed_successfully`, env from `.env` |
| `households` | `build: ./services/households` | port `8002:8000`, same |
| `ui` | `nginx:alpine` | `./ui:/usr/share/nginx/html:ro`, port `8080:80`. No Dockerfile, so it is not a service container. |

`db/init.sql` (idempotent): `IF DB_ID('personal') IS NULL CREATE DATABASE personal;` (same for households). `IF NOT EXISTS (… sys.sql_logins …) CREATE LOGIN personal_svc WITH PASSWORD = '$(PERSONAL_DB_PASSWORD)'`. In each database: `CREATE USER … FOR LOGIN …` + `db_ddladmin`, `db_datareader`, `db_datawriter`. No login can open the other database.
`.env.example` documents every variable with placeholder values. `.env` stays gitignored.

---

## 10. CI/CD (GitHub Actions)

### 10.1 `ci.yml`: `on: push (branches-ignore: [main])`, `pull_request`, `workflow_call`

1. **validate**: `check-jsonschema --schemafile system.schema.json system.yaml`. `openapi-spec-validator services/*/openapi.yaml`. Regenerate each OpenAPI file and `git diff --exit-code` so the committed file matches the code.
2. **test** (matrix `personal`, `households`): service container `mcr.microsoft.com/mssql/server:2022-latest`, wait for it, create the test DB, `pip install -r requirements.txt`, `ruff check`, `pytest --cov --cov-fail-under=70`.
3. **integration**: `docker compose up -d --build --wait`, `pytest tests/integration`, `docker compose logs` on failure, `down -v`.
4. **build**: `docker/build-push-action` for each service with `push: false`, `provenance: false`. A failed build fails CI.
CI never connects to Azure SQL.

### 10.2 `cd.yml`: `on: push: branches: [main]`

1. `ci: uses: ./.github/workflows/ci.yml`
2. `deploy: needs: ci`, `permissions: { id-token: write, contents: read, packages: write }`
   - `docker/login-action` to `ghcr.io` with `GITHUB_TOKEN`. Build and push `ghcr.io/sanad-albilleh/float-personal:${{ github.sha }}` and `float-households:${{ github.sha }}` (`provenance: false`, build-arg `GIT_SHA`).
   - `azure/login@v2` with `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (OIDC, no password).
   - `az containerapp secret set` for `database-url`, `token-secret`, `internal-api-key` (built from GitHub secrets), then `az containerapp update --image …:${{ github.sha }} --min-replicas 0 --max-replicas 1 --set-env-vars DATABASE_URL=secretref:database-url … HOUSEHOLDS_URL=https://… CORS_ORIGINS=https://sgealbillehieu2024ui.z<N>.web.core.windows.net GIT_SHA=${{ github.sha }}`.
   - Write `ui/config.js` with both Container App FQDNs (`az containerapp show --query properties.configuration.ingress.fqdn`).
   - Upload: `az storage blob upload-batch -d '$web' -s ui --overwrite` using the account key from `az storage account keys list` (Contributor can list keys. The data-plane role is not needed).
   - Health: loop for up to 5 minutes, `curl -fsS https://<app>/health` each 15 s for both services. Fail the run if either never returns 200.

### 10.3 Secrets and variables (GitHub)

Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `PERSONAL_DB_PASSWORD`, `HOUSEHOLDS_DB_PASSWORD`, `TOKEN_SECRET`, `INTERNAL_API_KEY`.
Variables: `PREFIX=sgealbilleh-ieu2024`, `RESOURCE_GROUP=rg-sgealbilleh-ieu2024`, `UI_STORAGE=sgealbillehieu2024ui`, `SQL_SERVER=sgealbilleh-ieu2024-sql`.
Before every commit: `git diff --cached` checked for passwords. If a secret ever leaks: rotate it within 24 h, update the GitHub secret, and log the incident in the README (§5).

---

## 11. Azure (one-time setup, every command copied into the README without passwords)

Run in **bash** (not zsh, see the guide's warning about `:r`).

1. `az login`, `az account set --subscription "Azure for Students"`. List allowed regions: `az policy assignment list --query "[?displayName=='Allowed resource deployment regions'].parameters"`. Pick one and use it for everything.
2. Register `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.Sql`, `Microsoft.Storage`, `Microsoft.ManagedIdentity`. Create `rg-sgealbilleh-ieu2024`.
3. Storage `sgealbillehieu2024ui` (StorageV2, Standard_LRS), `az storage blob service-properties update --static-website --index-document index.html`. Note the web endpoint → `CORS_ORIGINS`, `public_url`.
4. SQL server `sgealbilleh-ieu2024-sql`. Databases `sgealbilleh-ieu2024-personal-db` and `sgealbilleh-ieu2024-households-db`: `--edition GeneralPurpose --compute-model Serverless --family Gen5 --min-capacity 0.5 --capacity 1 --backup-storage-redundancy Local --use-free-limit true --free-limit-exhaustion-behavior AutoPause` (no `--auto-pause-delay`/`--max-size`). Firewall: allow Azure services. Open my IP, create contained users with `sqlcmd` (`CREATE USER personal_svc WITH PASSWORD = …` + 3 roles, same for households), close my IP.
5. Container Apps environment `sgealbilleh-ieu2024-env`. Apps `sgealbilleh-ieu2024-personal` and `sgealbilleh-ieu2024-households`: placeholder image `mcr.microsoft.com/k8se/quickstart:latest`, external ingress, target port 8000, min 0 / max 1, `--cpu 0.25 --memory 0.5Gi`. **No ingress CORS.**
6. Managed identity `sgealbilleh-ieu2024-github`, Contributor on the resource group only. Federated credentials for `repo:Sanad-AlBilleh/Float:ref:refs/heads/main` **and** the numeric-ID form if login complains.
7. GitHub secrets and variables (§10.3) with `gh secret set` / `gh variable set`.
8. Reader role on the resource group for `amartini@faculty.ie.edu` and `bserra@faculty.ie.edu`.
9. After the first CD run fails on the private GHCR packages (expected), make both packages public and re-run. That run is the "failed run that was fixed" evidence.

After this, nothing is changed in the portal. Only the pipeline deploys.

---

## 12. Documentation

- **`ADR.md`:** ADR 1–5 text unchanged. Set **ADR-1** to `Status: Superseded by 6` (one process + SQLite). Set **ADR-3** to `Status: Superseded by 7` for the SQLite-specific parts. ADR-2 stays (the seam held). New entries in the same format, on at least 3 dates:
  - **ADR-6 The split** (Wed 18): seam, what crosses it (D4), ADR-2 held, copied `shared/`, token auth.
  - **ADR-7 Data and migrations** (Thu 19): table ownership, foreign keys turned into plain IDs, idempotency + compensation, forward-only, recovery plan for a bad migration (fix-forward with a new file; restore with Azure SQL point-in-time restore to a new DB if data is damaged).
  - **ADR-9 Pipeline and testing** (Fri 20): CI gates, compose integration test vs stub, what is not tested (UI JS, Azure-only behaviour).
  - **ADR-8 Serverless hosting on Azure** (Fri 20 / Sat 21): resources and cost model, cold starts, DB resume (40613), startup migrations with one replica, what changes at 100× traffic (more replicas → migrations as a separate job, connection pooling, provisioned DB, caching member names).
  - **ADR-10 Not built: a gateway/BFF container** (Sat 21).
- **`AI_USAGE.md`:** a row per meaningful AI interaction, **including one per Dockerfile, compose, workflow and init.sql**, with "In my own words, how this works".
- **`system.yaml`** + **`system.schema.json`** (from Blackboard): both services, every env var with its default, secrets with `secret: true`, the calls in D4 with `timeout_s` and `on_failure`, and the Azure resource names.
- **`services/*/openapi.yaml`:** generated by `scripts/export_openapi.py` (`app.openapi()` → YAML), committed. Internal endpoints that the other service calls are included with the same shapes.
- **`README.md`:** run with compose, run one service alone, tests and coverage, how deployment works, the Azure setup (§11), the live URL, the secret-incident section (empty unless needed), the trimmed-UI note, and the AI-disclosure statement.
- **Report (4–5 pages, `docs/a2/report`):** before/after architecture diagrams, deployment diagram, DB diagram per service, migration evidence on Azure, partial-failure screenshot, links to a green CD run and a fixed failed run.

---

## 13. Day-by-day schedule

Every day: one branch, commits as each piece works, push, PR, merge. Merge commits count, so each day adds about 1 merge.

### Day 0: Tuesday 17 November (tonight, smallest)
Branch `docs/a2-plan`.
- [x] `Plan the Assignment 2 split, deployment and daily schedule`: this file and an AI_USAGE row.
- [x] PR + merge.

### Day 1: Wednesday 18 November: split, SQL Server, compose
Branch `feature/split-services`.
1. `Move the code into services/personal and services/households`: move packages (§4, §5), copy `shared/`, per-service `requirements.txt` and `pyproject.toml`, delete `app.py`/root manifest, per-service architecture test. Pure unit tests pass in both.
2. `Port the schema to SQL Server with per-service migrations`: `001_init.sql` ×2 (§7.1), new DB layer with `pymssql` + retry, runner with `schema_migrations`, port every query (placeholders, OUTPUT, OFFSET/FETCH, NOT EXISTS).
3. `Add Dockerfiles, db/init.sql and docker-compose`: §9. `docker compose up --build` from a clean clone works.
4. `Record ADR-6 (the split) and AI log rows`.
Evening: **Azure setup steps 1–8** (§11), the commands written into the README the same day (commit 5: `Document the initial Azure setup`).

### Day 2: Thursday 19 November: cross-seam, health, auth, UI part 1
Branch `feature/seam-and-health`.
1. `Replace cookie sessions with signed bearer tokens`: tokens, both services, CORS, remove `app/web` + templates + CSRF.
2. `Call across the seam with timeouts, idempotency and fallbacks`: `/internal/*` endpoints, clients, D4–D6, member-name cache logic.
3. `Add /health and per-request logs to both services`.
4. `Build the static UI: login, setup, dashboard, transactions`: `ui/`, `api.js` with cold-start handling, nginx in compose.
5. `Record ADR-7 (data and migrations), mark ADR-1/3 superseded, AI log rows`.

### Day 3: Friday 20 November: rest of UI, docs as data, CI, first deploy
Branch `feature/ui-ci`.
1. `Finish the static UI: bills, goals, budgets, households`.
2. `Port the API tests to SQL Server and add client, health and migration tests` (coverage ≥ 70% each).
3. `Add the cross-seam integration test against compose`.
4. `Export OpenAPI documents and write system.yaml`.
5. `Add the CI workflow` (validate, lint, test + coverage, integration, image builds). Green on the PR.
6. `Add the CD workflow`. **Merge → first deploy** (expected to fail on private GHCR, then fix: evidence). Live with `001` only.
7. `Record ADR-9 (pipeline and testing), AI log rows`.
Evening: create real data on Azure through the UI (data that must survive the migration). Screenshot it.

### Day 4: Saturday 21 November: migration on Azure, polish, fully deployed
Branch `feature/migrations-on-azure`.
1. `Add migrations that change tables holding data` (`002_member_name.sql`, `002_transaction_source.sql`) and their tests. Merge → CD deploys. Capture the startup log line, the CD run link and the data before/after.
2. `Handle the partial-failure and cold-start paths in the UI`: verify with `docker compose stop personal` / `households` and after Azure idle. Screenshots.
3. `Record ADR-8 (serverless hosting) and ADR-10 (not built)`.
4. `Complete the README and system.yaml with the live URL`.
End of day: everything in §1–§12 is deployed and working at the live URL.

### Day 5: Sunday 22 November: review, fixes, report, submission
Branch `fix/review` (+ `docs/report`).
1. Fixes from my own walkthrough of the live app (one commit per fix).
2. `Write the Assignment 2 report` (diagrams, evidence, links).
3. Final AI log rows. Final check of commit counts (`git log --date=short --format=%ad main | sort | uniq -c`).
4. Merge, wait for green CD, then `git tag submission <sha> && git push origin submission`.

### Commit budget (content + merge)

| Day | Content | Merges | Total |
|---|---|---|---|
| Tue 17 | 1 | 1 | 2 |
| Wed 18 | 5 | 1 | 6 |
| Thu 19 | 5 | 1 | 6 |
| Fri 20 | 7 | 1–2 | 9 |
| Sat 21 | 4 | 1–2 | 6 |
| Sun 22 | 3–5 | 1–2 | 5 |
| **Total** | | | **~34** |

Largest day (Fri, 9) ≈ 26%, under the 40% limit. 6 distinct days, ≥ 12 commits. **No day can be skipped.**

---

## 14. Risks

| Risk | Plan |
|---|---|
| Porting ~28 tables and every query to T-SQL takes longer than one day | Port per service with the DB tests as the checklist. Drop the trimmed features' queries first if short on time. |
| Free SQL offer not in my region | Put the SQL server in another allowed region (the guide allows this). |
| `pymssql` on Python 3.14 | Use `python:3.13-slim`. Check day 1. |
| OIDC subject mismatch | Register both name and numeric-ID subjects. Run setup in bash. |
| Migration evidence needs data on Azure **before** `002` | First deploy must be on Friday at the latest. `002` is held back until Saturday. |
| `system.schema.json` comes from Blackboard | Download it by Friday. CI validation depends on it. |
| Comprehension check | Each evening, re-read the day's Dockerfile/workflow/SQL lines and write the AI log "in my own words" column myself. |
