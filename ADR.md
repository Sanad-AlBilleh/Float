# Architecture Decision Records

These are my five main decisions. I wrote each one on the day I made it (1, 2 and 3 October 2026). On 4 October I rewrote them in the format the assignment asks for and in simpler words. The decisions did not change.

## 1. Python, FastAPI, Jinja2 and SQLite in one process
Date: 2026-10-01
Status: Decided
Context: Float has to start from a fresh clone with one command (`python app.py`), save its data in SQLite and run as one process. I also have to explain the code on paper, and Python is the language I know best.
Decision: I used FastAPI to serve both the HTML pages (built with Jinja2 templates) and a JSON API, all from one Uvicorn worker. I talk to SQLite with Python's built-in `sqlite3` module and write the SQL myself. Passwords are hashed with the built-in `hashlib.scrypt`, so the app needs only 4 packages to run (FastAPI, Uvicorn, Jinja2, python-multipart) plus 4 for testing.
Alternatives considered: Django comes with an ORM, an admin site and logins that I mostly would not use, and the ORM hides the SQL I need to understand. Flask is about the same size as FastAPI but does not check request data with types or make API docs for me. A React front end with a separate API would mean two processes, which the assignment does not allow. SQLAlchemy would save me some SQL, but my money rules are easier to see in plain SQL.
Consequences: I can see and test every query, and the pages are plain HTML forms with no JavaScript at all. SQLite only lets one write happen at a time, but that is fine for one flat of students: the dashboard took 48 ms with 16,000 transactions.

## 2. Domains that never import each other, joined by an application layer
Date: 2026-10-01
Status: Decided
Context: The assignment wants at least two parts of the backend that could become separate services later. Some actions touch more than one part. For example, paying a bill changes Planning (the bill) and the Ledger (the expense), and confirming a settlement writes into two people's ledgers.
Decision: I split the code into five packages: Identity, Ledger, Planning, Households and Insights. Other code can only use a package through its `api.py` file, and a test (`tests/test_architecture.py`) fails if one package imports another. The only exception is Insights, which may read the others through their `api.py` because it only does calculations. Actions that touch more than one package live in `app/application/` and run inside one database transaction that also writes an audit record.
Alternatives considered: One big package with shared models would be faster to start, but nothing would stop Planning from reading the Ledger's tables, so the separation would only exist on paper. Real separate services would need network calls between them, which the one-container rule does not allow.
Consequences: Paying a bill or confirming a settlement either fully happens or does not happen at all. The application layer is where I would cut the app apart later: if Households became its own service, those functions would turn into API calls. The packages still share one database and a few foreign keys, which is the price of keeping everything in one app.

## 3. Database: money in cents, strict tables, and payment links instead of "paid" flags
Date: 2026-10-02
Status: Decided
Context: Every number Float shows comes from rows in the database. A rounding error, a bill saved twice, or a "paid" flag that does not match the real expense would make the safe-to-spend number wrong.
Decision: All money is stored as whole cents (`INTEGER`) in `STRICT` tables, with `CHECK` rules that limit amounts to €1,000,000. A bill counts as paid only when its `paid_transaction_id` points at the expense that paid it, and that column is `UNIQUE` so one expense can only pay one bill. Each bill date is stored once per series (`UNIQUE (series_id, scheduled_date)`). Triggers stop anyone from changing a goal movement, or changing or deleting an audit record. Rows that people edit have a `version` number so two edits at the same time cannot overwrite each other.
Alternatives considered: Floating point numbers (REAL) can round wrongly, for example 0.1 + 0.2 is not exactly 0.3. A `status` column saying "paid" is simpler but can say "paid" when the expense is missing. Working out bills on the fly without saving them would leave nowhere to store an edited amount or a payment.
Consequences: Paying, undoing and splitting a bill are each one transaction, and creating bills again can never make duplicates. Reading is a little slower because Float works out each bill's status and adds up goal movements, but that is fine at a student's scale. Planning cannot move to its own database without replacing its foreign key to the `transactions` table.

## 4. Testing: pure functions, property tests, a real SQLite file and planted bugs
Date: 2026-10-03
Status: Decided
Context: Float is only useful if its numbers are right, and money bugs hide in cases I would not think to test by hand, like odd amounts, ties, many flatmates or long chains of actions. The assignment asks for 70% coverage of the core logic, but coverage only proves a line ran, not that it is right.
Decision: I put every calculation in a pure function (no database) and tested it against the worked examples in the SRS (Fixtures A to G). I used Hypothesis to try many random inputs for rules that must always hold: splits add up to the exact amount, household balances add up to zero, and paying a bill does not change safe-to-spend. Everything that touches the database is tested on a real temporary SQLite file. After each feature I planted small bugs in the code (like changing `<` to `<=`) to check that a test fails.
Alternatives considered: Only hand-written examples would have missed bugs the planted bugs found, like a bill due exactly on payday. Faking (mocking) the database would not test the constraints and triggers my correctness depends on.
Consequences: The 604 tests run in under a minute with nothing else installed, and cover 97% of the business code. I tested the HTML templates and CSS less, because they hold no money logic. I checked them with page tests and by looking at the app in a browser.

## 5. Not built: a background scheduler
Date: 2026-10-03
Status: Decided
Context: Some features depend on time passing. Recurring bills have to exist before they are due, and an alert should show up when a bill is close. The usual answer is a cron job or a background worker.
Decision: Float has no scheduler. When a page needs bills, `ensure_materialized` creates any missing bill dates with `INSERT ... ON CONFLICT DO NOTHING`, so running it twice is harmless. Alerts are worked out again when the dashboard or alerts page opens and after every change.
Alternatives considered: Cron or Celery needs a second process and a message broker, which the assignment does not allow. A scheduler thread inside the app would write to SQLite at the same time as user requests, which causes locking problems, and it does nothing while the app is off anyway.
Consequences: Nothing happens while nobody is using Float, so an alert appears the next time someone opens the app, not at an exact time. There are no emails or push notifications. If I ever need them, a scheduler could call the same functions without rewriting them.
