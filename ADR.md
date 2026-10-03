# Architecture decision records

Float keeps exactly five decision records, as the assignment requires. Each one is written on the day its decision was made or confirmed in code, and none is backdated. Every record covers the context, the decision, the alternatives considered, and the consequences.

| ID | Decision | Date |
|---|---|---|
| ADR-1 | Python, FastAPI, Jinja2, and SQLite in one process | 2026-10-01 |
| ADR-2 | Three domains behind narrow interfaces, coordinated by an application layer | 2026-10-01 |
| ADR-3 | Schema: integer cents, STRICT tables, payment links, and append-only history | 2026-10-02 |
| ADR-4 | Testing strategy: pure rules, properties, real SQLite, and mutation checks | 2026-10-03 |
| ADR-5 | Deliberate omission: no background scheduler | 2026-10-03 |

## ADR-1: Python, FastAPI, Jinja2, and SQLite in one process

- **Date:** 2026-10-01. The student chose Python/FastAPI on 2026-09-28; the build confirmed the rest of the stack on 30 September and 1 October.
- **Status:** Accepted

**Context.** Float is a course project. It must start from a fresh clone with one command (`python app.py`), keep its data across restarts, and be explained line by line in a written check. The assignment rules out separate frontend and backend processes, managed services, and authored Docker/CI/IaC (NFR-04).

**Decision.**
- **Web:** FastAPI (on Starlette) serves server-rendered Jinja2 pages, static files, and later a JSON API, from a single Uvicorn worker.
- **Database:** SQLite through the standard-library `sqlite3` module, in WAL mode, with STRICT tables and hand-written parameterized SQL. Numbered migration files are applied once at startup.
- **Dependencies:** one `requirements.txt` with pinned versions: FastAPI 0.142, Uvicorn, Jinja2, python-multipart, pytest, pytest-cov, Hypothesis, and httpx2. httpx2 replaced httpx after Starlette 1.7 deprecated httpx for its test client.
- **Passwords:** hashed with the standard library's `hashlib.scrypt`, so no extra crypto dependency.

**Alternatives considered.**
- **Django:** ORM, auth, and admin included, but much would go unused and be hard to explain, and the ORM hides the SQL.
- **Flask:** a similar size, but without typed request handling or the generated OpenAPI schema the P1 API needs.
- **A single-page app with a separate API:** breaks the one-process rule and doubles the code to explain.
- **SQLAlchemy:** less SQL to write, but the integer-cent rules, CHECK constraints, and version-checked updates are clearer as plain SQL.

**Consequences.**
- Every query is visible and tested, and the schema enforces the same rules as the code.
- Pages are plain HTML forms using post/redirect/get, with little or no JavaScript.
- SQLite allows one writer at a time. That is enough for one flat on a home network; NFR-05 will measure it.
- Pinned versions have to be upgraded deliberately.

## ADR-2: Three domains behind narrow interfaces, coordinated by an application layer

- **Date:** 2026-10-01
- **Status:** Accepted

**Context.** The assignment asks for persistent backend domains with clear boundaries, and the professor asked for a more complex backend. Float's money rules cross areas: paying a bill touches the Ledger and Planning, and confirming a settlement writes two people's ledgers.

**Decision.**
- **Packages:** three business domains (Ledger, Planning, Households) plus Identity and Insights. Each package has:
  - `rules.py`: pure functions;
  - `repository.py`: SQL on its own tables only;
  - `service.py`;
  - `api.py`: the only module other code may import.
- **Import rules:** domains never import each other. Insights may import only `api.py` modules, and `app/shared` does no I/O. `tests/test_architecture.py` reads every import statement and fails the build on a violation.
- **Writes:** cross-domain writes run in the application layer, inside one `BEGIN IMMEDIATE` transaction, and services never commit. Every financial or membership change writes an audit event in that same transaction.
- **Failures that must persist:** when a failure still has to be recorded, such as a failed login, the service returns an outcome instead of raising. The application layer commits the attempt first, then reports the failure.

**Alternatives considered.**
- **One package with shared models:** faster to start, but nothing would stop Planning from reading Ledger tables, so the boundaries would exist only on paper.
- **Separate services:** real isolation, but it needs network calls, distributed transactions (sagas or an outbox), and deployment work the assignment rules out.

**Consequences.**
- A bill payment or settlement either happens completely or not at all, inside a single database transaction instead of a saga.
- Foreign keys from Planning and Households into `transactions` and `users` couple the schemas; this is the accepted price of one database (SRS §6.5).
- If a domain were ever split out, the application-layer coordinators are the seam. They would become sagas with a transactional outbox. This is not implemented.

## ADR-3: Schema: integer cents, STRICT tables, payment links, and append-only history

- **Date:** 2026-10-02, when migration `0008_planning.sql` added bills, goals, and budgets on top of the Day 0–1 tables.
- **Status:** Accepted

**Context.** Every number Float shows is derived from stored rows: safe-to-spend subtracts bills, savings, and plans from a balance, and the forecast projects them forward. A rounding error, a duplicated bill, or a "paid" flag that disagrees with the ledger would make the headline number wrong. The schema has to make those mistakes impossible, not just unlikely.

**Decision.**
- **Money is integer cents.** Every amount column is `INTEGER` with a `CHECK` on its range (±€1,000,000.00). Input is parsed exactly; floats never touch money.
- **STRICT tables with constraints.** Every table is `STRICT`, so SQLite refuses a text value in an integer column. `CHECK`, `UNIQUE`, and foreign keys repeat the service rules, so a bug in Python still cannot store an impossible row. For example, a series cannot have both an end date and a count, and a transaction cannot be income with a category.
- **Payment links instead of status flags.** An occurrence is paid exactly when `paid_transaction_id` points at its expense. That column is `UNIQUE` and `ON DELETE RESTRICT`, so one expense pays at most one bill and cannot be deleted while it is linked. Status (`paid`, `skipped`, `overdue`, `reserved`, `upcoming`) is derived on read, so there is no second field to drift out of sync.
- **`scheduled_date` versus `due_date`.** Each occurrence keeps the date its rule generated as an immutable uniqueness key, `UNIQUE (series_id, scheduled_date)`, separate from its editable due date. Materialization inserts with `ON CONFLICT DO NOTHING`, so repeating it never duplicates a bill, even after a due date moves.
- **Append-only history.** Goal movements and audit events are never updated: triggers abort an `UPDATE` (and a `DELETE` on audit events). A goal's protected amount is the sum of its movements, and a mistake is reversed by an opposite movement.
- **Versions on editable rows.** Series, occurrences, goals, and transactions carry a `version`. Every update is `WHERE id = ? AND version = ?`, and a zero row count means someone else changed it first.
- **Cross-domain foreign keys.** `bill_occurrences.paid_transaction_id` references the Ledger's `transactions`, and Planning's tables reference `users` and `categories`. The code still crosses domains only through `api.py` (ADR-2); the foreign keys are a documented monolith tradeoff (SRS §6.5).

**Alternatives considered.**
- **Decimal or REAL amounts:** REAL rounds in binary, and Python `Decimal` would need text columns and conversions everywhere. Integer cents are exact and fast.
- **A `status` column on occurrences:** simpler queries, but it could say "paid" while the expense is missing, or the reverse. The link cannot disagree with itself.
- **Generating occurrences on the fly instead of storing them:** no duplicates to prevent, but nowhere to keep an edited amount, a moved due date, a skip, or a payment link.
- **A mutable `protected_cents` column on goals:** one fewer query, but no history, and a lost update could silently change savings.

**Consequences.**
- Paying, undoing, and splitting a bill are each one transaction that either fully happens or does not. Fault-injection and mutation tests check this.
- Reads do a little more work: status is computed, and protected savings is a `SUM`. That is fine at a student's data volume, and NFR-05 measures it on Day 4.
- Splitting a series ("this and future") has to follow SRS §4.2 exactly: it shortens the old series, deletes only unpaid later rows, and creates a new series. Paid history is never rewritten.
- Planning cannot be moved to another database without replacing the foreign key to `transactions` with an application-level check.

## ADR-4: Testing strategy: pure rules, properties, real SQLite, and mutation checks

- **Date:** 2026-10-03, after the household money rules (the riskiest code) were built test-first.
- **Status:** Accepted

**Context.** Float's value is its numbers. A cent lost in a three-way split, a bill counted twice, or a settlement confirmed twice would be a real bug for real flatmates. Hand-picked examples catch the cases the author thought of, but money bugs hide in the cases nobody thought of: odd amounts, ties, many members, and long sequences of actions. The assignment asks for at least 70% coverage of the business modules, but coverage only proves a line ran, not that a test would notice it was wrong.

**Decision.**
- **Pure rules first.** Every calculation in SRS §4 is a pure function: recurrence, allocation, nets and simplification, safe-to-spend, goal plans, the forecast, unusual expenses, and alert rules. Each is unit-tested with injected dates and integer cents, including every worked fixture (A–G) from SRS §4.10.
- **Properties with Hypothesis.** Hypothesis generates many random cases for the invariants that must always hold:
  - recurrence output is sorted, unique, and consistent across windows;
  - split shares add up to the amount and stay within a cent of exact;
  - household nets sum to zero and the settle-up plan clears everyone in at most n − 1 transfers;
  - **conservation (SRS §4.5):** for random sequences of bill payments, household bill payments, confirmed settlements, and goal protection, every user's discretionary money changes by exactly minus the change in what they are owed.
- **Real SQLite, not mocks.** Services and workflows run against a temporary SQLite file with the real migrations, so constraints, triggers, and transactions are tested too. Fault injection (a failure after the ledger write) proves that a workflow rolls back completely, and two connections race on the same settlement to prove exactly one transition wins.
- **HTTP tests.** FastAPI's test client drives the pages and the JSON API: an authorization matrix (other people's records are 404, non-owners get 403), CSRF rejection, and Fixture A on the real dashboard and forecast pages.
- **Mutation spot-checks.** After each feature, small deliberate bugs are injected into the new code (a `<` turned into `<=`, a check removed), and the relevant tests must fail. Survivors either get a new test or are recorded as equivalent (the change cannot alter behaviour, for example because a SQL condition repeats a Python check).
- **Coverage as a floor, not a goal.** The 70% target is measured over the business modules only (identity, ledger, planning, households, insights, application, shared), not the templates or web glue.

**Alternatives considered.**
- **Examples only:** simpler and readable, but they missed exactly the boundary bugs the mutation checks later found (a bill due on payday, a runway equal to the days left, a tie for the lowest point).
- **Mocking the database:** faster, but it would not test the constraints, triggers, `ON CONFLICT` clauses, and version-checked updates that the correctness depends on.
- **A full mutation-testing tool such as mutmut:** more thorough, but slow on a 560-test suite and harder to explain. Targeted manual mutants kept the feedback loop under a minute.

**Consequences.**
- The suite runs in under a minute on a laptop and needs no services.
- Hypothesis makes some tests slower (the conservation property builds a fresh flat for each example), so its example counts are kept small and deadlines are disabled for that test.
- Mutation checks found real gaps on every build day: 19 on 2 October and more on 3 October. Each one became a test.
- Coverage of the business modules is reported in the README with the date it was measured.

## ADR-5: Deliberate omission: no background scheduler

- **Date:** 2026-10-03, when the last time-based feature (alerts) was built without one.
- **Status:** Accepted

**Context.** Several features depend on time passing: recurring bills must exist before they are due, alerts should appear when a bill is due soon, and a new cycle starts on payday. The usual solution is a background job (cron, Celery, or an in-process scheduler) that wakes up and does the work.

**Decision.** Float has **no background scheduler and no worker process**. Instead:
- **Bills are materialized lazily.** Before any page or API call that depends on bills, `ensure_materialized` generates the occurrences up to the end of the horizon, inside a transaction, with `INSERT … ON CONFLICT DO NOTHING`. Repeating it, concurrently or after a restart, never creates a duplicate (ADR-3).
- **Alerts are evaluated on demand,** when the dashboard or the alert centre loads and after every successful change, in their own transaction once the change has committed. Evaluation is idempotent: running it twice without data changes adds nothing.
- **Dates come from an injected clock,** so "today" is always the moment a request is handled, and tests can move time.

**Alternatives considered.**
- **A cron job or Celery worker:** would need a second process, a broker, and deployment work that the assignment rules out (NFR-01, NFR-04), and it would be another thing to explain line by line.
- **An in-process scheduler thread (for example APScheduler):** one process, but a thread that writes to SQLite while requests also write adds locking and testing problems, and it does nothing while the app is stopped anyway.

**Consequences.**
- Nothing happens while nobody uses Float. An alert for a bill due today appears the next time someone opens the app, not at 9:00. For a personal finance app opened a few times a day, that is acceptable, and the README says so.
- Every read that depends on bills does a little extra work: usually nothing, because the watermark is already at the horizon.
- There are no emails or push notifications; alerts are in-app only (the PRD already excludes email, SMS, and push notifications).
- If Float ever needed time-based notifications, a scheduler could call the same idempotent functions; nothing would need to be rewritten.
