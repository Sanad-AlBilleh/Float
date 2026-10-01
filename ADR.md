# Architecture decision records

Float keeps exactly five decision records, as the assignment requires. Each one is written on the day its decision was made or confirmed in code, and none is backdated. Every record covers the context, the decision, the alternatives considered, and the consequences.

| ID | Decision | Date |
|---|---|---|
| ADR-1 | Python, FastAPI, Jinja2, and SQLite in one process | 2026-10-01 |
| ADR-2 | Three domains behind narrow interfaces, coordinated by an application layer | 2026-10-01 |
| ADR-3 | Schema: integer cents, STRICT tables, payment links (planned for 2 October) | — |
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
