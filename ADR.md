# Architecture decision records

Float keeps exactly five decision records, as the assignment requires. Each one is written on the day its decision was made or confirmed in code, and none is backdated. Every record covers the context, the decision, the alternatives considered, and the consequences.

| ID | Decision | Date |
|---|---|---|
| ADR-1 | Python, FastAPI, Jinja2, and SQLite in one process | 2026-10-01 |
| ADR-2 | Three domains behind narrow interfaces, coordinated by an application layer | 2026-10-01 |
| ADR-3 | Schema: integer cents, STRICT tables, payment links, and append-only history | 2026-10-02 |
| ADR-4 | Testing strategy (planned for 3 October) | — |
| ADR-5 | Deliberate omission (planned for 3 October) | — |

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
