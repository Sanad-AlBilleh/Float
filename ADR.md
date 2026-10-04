# Architecture Decision Records

Five decisions, each written on the day I made it (1, 2 and 3 October 2026). On 4 October I shortened them into the format the assignment asks for. The decisions themselves did not change.

## 1. Python, FastAPI, Jinja2 and SQLite in one process
Date: 2026-10-01
Status: Decided
Context: Float has to start from a fresh clone with one command (`python app.py`), keep its data in SQLite, run as one process, and be code I can explain on paper. I already know Python best.
Decision: FastAPI serves server-rendered Jinja2 pages and a JSON API from one Uvicorn worker, and talks to SQLite through the standard `sqlite3` module with hand-written SQL. Passwords use the standard library's `hashlib.scrypt`, so there are only 4 runtime packages (plus 4 for testing).
Alternatives considered: Django brings an ORM, admin and auth I would mostly not use, and the ORM hides the SQL I need to explain. Flask is similar in size but has no typed request models or generated API docs. A React front end with a separate API would break the one-process rule. SQLAlchemy would save some SQL but make the integer-cent rules and version-checked updates harder to see.
Consequences: Every query is visible and tested, and the pages are plain HTML forms that need almost no JavaScript. SQLite allows one writer at a time, which is fine for a flat of students (dashboard p95 was 48 ms on 16,000 transactions).

## 2. Domains that never import each other, joined by an application layer
Date: 2026-10-01
Status: Decided
Context: The assignment wants at least two domains that could become separate services later. Some actions cross domains: paying a bill touches Planning and the Ledger, and confirming a settlement writes two people's ledgers.
Decision: Identity, Ledger, Planning, Households and Insights are separate packages. Each one only exposes `api.py`, and `tests/test_architecture.py` fails the build if one domain imports another (only Insights may read other domains' `api.py`, because it just calculates). Workflows that cross domains live in `app/application/` and run inside one `BEGIN IMMEDIATE` transaction with an audit event.
Alternatives considered: One package with shared models would be faster to start, but nothing would stop Planning reading Ledger tables, so the seams would only exist on paper. Real separate services would need network calls and sagas, which the single-container rule forbids.
Consequences: A bill payment or a settlement either fully happens or does not happen at all. The application layer is the seam: if Households became its own service, those coordinators would turn into API calls with an outbox. The domains still share one database and some foreign keys, which is the price of a monolith.

## 3. Schema: integer cents, STRICT tables and payment links instead of status flags
Date: 2026-10-02
Status: Decided
Context: Every number Float shows comes from stored rows, so a rounding error, a bill stored twice, or a "paid" flag that disagrees with the ledger would make safe-to-spend wrong.
Decision: All money is `INTEGER` cents in `STRICT` tables with `CHECK` limits. A bill occurrence is paid exactly when its `paid_transaction_id` points at the expense that paid it (`UNIQUE`, `ON DELETE RESTRICT`), and status is worked out when reading. Occurrences are unique on `(series_id, scheduled_date)`, goal movements can't be updated and audit events can't be updated or deleted (triggers block both), and editable rows carry a `version` column.
Alternatives considered: REAL amounts round in binary and Decimal would need text columns. A `status` column on occurrences is simpler to query but can say "paid" while the expense is missing. Generating bills on the fly without storing them leaves nowhere to keep an edited amount or a payment link.
Consequences: Paying, undoing and splitting a bill are each one transaction, and repeating bill generation can never create duplicates. Reads do a little more work (status is computed, protected savings is a SUM), and Planning cannot move to another database without replacing its foreign key to `transactions`.

## 4. Testing: pure rules, property tests, real SQLite and mutation checks
Date: 2026-10-03
Status: Decided
Context: Float's value is its numbers, and money bugs hide in cases nobody writes by hand: odd amounts, ties, many flatmates and long sequences of actions. The assignment asks for 70% coverage of the core logic, but coverage only proves a line ran.
Decision: I put every calculation in pure functions and unit-test them against the worked examples (Fixtures A to G) in the SRS. Hypothesis checks the rules that must always hold (splits add up, household balances sum to zero, paying a bill never changes safe-to-spend). Services run against a real temporary SQLite file, and after each feature I inject small bugs to check the tests catch them.
Alternatives considered: Examples only would have missed the boundary bugs that mutation checks found, like a bill due exactly on payday. Mocking the database would not test the constraints, triggers and `ON CONFLICT` clauses the correctness depends on.
Consequences: The suite runs in under a minute with no services and reaches 97% coverage of the business modules. I left the HTML templates and CSS thinner, because they hold no money logic and are covered by page tests and checking them in a browser.

## 5. Not built: a background scheduler
Date: 2026-10-03
Status: Decided
Context: Some features depend on time passing: recurring bills must exist before they are due and alerts should appear when a bill is close. The usual answer is a cron job or a worker.
Decision: There is no scheduler. Bills are generated lazily and idempotently (`ensure_materialized` with `INSERT ... ON CONFLICT DO NOTHING`) when a page needs them, and alerts are recalculated when the dashboard or alert page opens and after every change.
Alternatives considered: Cron or Celery needs a second process and a broker, which the assignment forbids. An in-process scheduler thread would write to SQLite at the same time as requests, adding locking problems, and it does nothing while the app is stopped anyway.
Consequences: Nothing happens while nobody uses Float, so an alert appears the next time someone opens the app, not at a set time, and there are no emails or push notifications. If that is ever needed, a scheduler could call the same idempotent functions.
