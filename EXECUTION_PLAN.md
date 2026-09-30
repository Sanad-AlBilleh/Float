# Float v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Float v0.2 as specified in `PRD.md` and `SRS.md`, one working, tested slice per day from 30 September to 3 October 2026, with 4 October reserved for testing, bug fixes, and polish.

**Architecture:** A modular monolith with one FastAPI process, one SQLite file, and server-rendered Jinja2 pages (plus a JSON API in P1). Three domains (Ledger, Planning, Households) and two supporting modules (Identity, Insights) never import each other. An application layer runs cross-domain workflows in one `BEGIN IMMEDIATE` transaction. All money is integer cents and every date-dependent rule receives an injected clock.

**Tech Stack:** Python 3.12+ (developed on 3.14), FastAPI 0.142, Starlette 1.7, Uvicorn, Jinja2, python-multipart, SQLite through the standard `sqlite3` module (STRICT tables, WAL), pytest, pytest-cov, Hypothesis, and httpx2 (the transport Starlette's test client prefers).

**Spec:** `SRS.md` v0.2 (exact rules, fixtures, schema) and `PRD.md` v0.2 (scope and priorities). `planned-commits.md` is the daily commit schedule this plan follows.

## Global Constraints

Copied from the SRS. Every task implicitly includes this section.

- Money is integer cents. Parse input exactly and reject more than two decimal places; never use `float` for money. Maximum magnitude is €1,000,000.00 (100,000,000 cents). (SRS §2)
- Dates are ISO `YYYY-MM-DD`; timestamps are UTC text. "Today" comes from an injected clock in `APP_TIMEZONE`, default `Europe/Madrid`. (SRS §2)
- Run as one process via `python app.py`, bound to `0.0.0.0`, reading `PORT` (default 8000), with one Uvicorn worker and no reload subprocess. (NFR-01)
- The database is `DATA_DIR/float.sqlite3` (`DATA_DIR` defaults to `./data`). Startup creates it, enables WAL, and applies migrations idempotently. (NFR-02)
- Exactly one dependency manifest: `requirements.txt`. No `pyproject.toml`, Pipfile, or per-folder manifests. (NFR-03)
- No mandatory network calls, managed services, background workers, schedulers, Dockerfiles, CI, or IaC. (NFR-04)
- Configuration comes only from `PORT`, `DATA_DIR`, `APP_TIMEZONE`, `COOKIE_SECURE`, `SESSION_IDLE_HOURS` (48), and `SESSION_MAX_DAYS` (14), optionally via `.env`. (NFR-06)
- Domains never import each other; Insights imports only `app.<domain>.api`; `app/shared` never touches I/O. An architecture test enforces this. (SRS §6.1)
- Every connection sets `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000`. Writes happen inside `transaction(conn)` (`BEGIN IMMEDIATE`), and services never commit. (SRS §6.4)
- Mutations only via POST (HTML) or POST/PUT/PATCH/DELETE (API), never GET. Successful HTML form posts redirect. (SRS §8.1)
- Coverage is at least 70% over `app.identity`, `app.ledger`, `app.planning`, `app.households`, `app.insights`, `app.application`, and `app.shared`. (NFR-08)
- Honesty rules: never commit work built on an earlier day, never backdate, and log AI use and decisions the day they happen. (`planned-commits.md`)

---

## How to execute this plan

Each day follows the same loop:

1. `git checkout main && git pull --ff-only`, then `git checkout -b build/<date>-<slug>` using the branch name from `planned-commits.md`.
2. Activate the environment: `source .venv/bin/activate`. If the virtualenv is missing, create it with `python3 -m venv .venv && pip install -r requirements.txt`.
3. Work task by task. Write the failing test, run it and watch it fail for the expected reason, write the minimal implementation, then run it and watch it pass.
4. Run the whole suite before each commit: `pytest -q`. Commit only when everything passes. Commit messages are the ones in `planned-commits.md`.
5. At the end of the day, update `AI_USAGE.md` and any ADR, push, open a PR (`gh pr create`), merge it with a merge commit (`gh pr merge --merge`), and tick the day's boxes in `planned-commits.md`.

**Code blocks marked with a first line such as `# file: path`, `-- file: path`, `{# file: path #}`, or `/* file: path */` are complete files.** Write them to that path without the marker line. Unmarked blocks are excerpts or snippets.

## File structure (all days)

| Path | Responsibility | Day |
|---|---|---|
| `app.py` | Entry point: loads settings, runs Uvicorn with one worker | 0 |
| `requirements.txt`, `pytest.ini`, `.gitignore` | Dependencies, test configuration, ignored runtime files | 0 |
| `app/config.py` | `Settings`, `load_settings()`, `.env` reader, `ConfigError` | 0 |
| `app/main.py` | `create_app(settings, clock)`: database init, static files, routers, middleware | 0 (grows daily) |
| `app/db/connection.py` | `connect()` with pragmas; `enable_wal()` | 0 |
| `app/db/unit_of_work.py` | `transaction(conn)`: `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` | 0 |
| `app/db/migrations.py` + `app/db/migrations/NNNN_*.sql` | Numbered migrations applied once; `initialize_database()` | 0 (one file per domain per day) |
| `app/shared/errors.py` | `ValidationError`, `NotFoundError`, `PermissionDeniedError`, `ConflictError` | 0 |
| `app/shared/money.py` | `parse_money`, `format_money`, `cents_to_input`, `MAX_CENTS` | 0 |
| `app/shared/clock.py` | `Clock`, `SystemClock`, `FixedClock`, UTC text helpers | 0 |
| `app/shared/dates.py` | `cycle_for`, `Cycle`, `scheduled_date`, `allowance_dates`, `parse_iso_date` | 0 |
| `app/shared/recurrence.py` | `Rule`, `expand`, `candidate`, `count_before`, `split_rule` | 0 (`split_rule` on day 2) |
| `app/identity/{rules,repository,service,api}.py` | Usernames, scrypt, tokens, throttling, sessions | 1 |
| `app/ledger/{rules,repository,service,api}.py` | Ledger settings, transactions, balance, expense rows, linked writes | 1 |
| `app/planning/{rules,repository,service,api}.py` | Planning settings, bill series/occurrences, goals, budgets, goal plan | 1–2 |
| `app/households/{rules,repository,service,api}.py` | Households, invitations, shared expenses, splits, nets, settlements, household bills | 3 |
| `app/insights/{safe_to_spend,forecast,consumption,anomaly,alerts,repository,api}.py` | Pure composition rules plus alert persistence | 2–3 |
| `app/application/{context,audit,authz,accounts,setup,transactions,bills,goals,households,dashboard,alerts}.py` | Use cases, coordinators, authorization, audit | 1–3 |
| `app/web/{templating,middleware,security,deps,forms,routes,auth,setup,transactions,bills,goals,households,dashboard,alerts}.py` | HTML routes, sessions, CSRF, headers, request IDs | 0–3, polished on 4 |
| `app/web/templates/*.html`, `app/web/static/float.css` | Jinja2 templates and one stylesheet | 0–3, polished on 4 |
| `app/api/v1/*.py` | JSON API routers, problem+json, idempotency keys (P1) | 3 |
| `tests/…` | Mirrors `app/`; plus `tests/factories.py`, `tests/scenarios/flat_3b.py`, and `tests/test_architecture.py` | 0–4 |
| `ADR.md`, `docs/report.md` | Five ADRs; the 4–5 page report | 1–4 |

## Conventions used by every task

**Layers.** A request flows: web or API route → application use case → domain service → domain repository → SQLite.

- *Routes* parse form or JSON input into typed values, collecting `ValidationError`s so a form can be re-rendered with every message.
- *Use cases* open `transaction(conn)`, check authorization, call services, and write audit events.
- *Services* validate domain rules and call repositories. They never commit.
- *Repositories* hold parameterized SQL for their own domain's tables only.
- *`rules.py`* files are pure functions with no I/O, tested without a database.

**Public interfaces.** Each domain's `api.py` re-exports the dataclasses and functions other packages may use. Code outside a domain, including the application and web layers, imports only that `api.py`, never the domain's `service`, `repository`, or `rules` modules.

**Errors.** Raise `ValidationError({field: message})` for bad input. Raise `NotFoundError` for missing records and for other people's records (FR-04 returns 404 for both). Raise `PermissionDeniedError` for a member without the right role (403) and `ConflictError` for stale versions or finished state transitions (409).

**Versions.** Every mutable row has `version INTEGER NOT NULL DEFAULT 1`. Updates use `UPDATE … SET …, version = version + 1 WHERE id = ? AND version = ?`, and zero affected rows raises `ConflictError`. HTML forms carry `version` in a hidden field.

**Timestamps.** `created_at`, `updated_at` and similar columns hold `to_utc_text(clock.now_utc())`. Business dates (`occurred_on`, `due_date`) hold `date.isoformat()`.

**Test data.** `tests/factories.py` (day 1) creates users, completed setup, and transactions directly through services. `tests/scenarios/flat_3b.py` (day 3) builds SRS Fixture A through application use cases and is reused by the dashboard, forecast, and conservation tests.

---

## Day 0 — Wednesday 30 September: foundation

**Deliverable:** a runnable app (`python app.py` serves a home page and `/healthz`) with configuration, SQLite migrations, a unit of work, and the pure money, cycle-date, and recurrence rules every later day depends on, all tested. Covers NFR-01, NFR-02, NFR-03, NFR-06, FR-08 (seed), and SRS §4.1–4.2.

### Task 0.1: Planning documents and approval status

**Files:**
- Create: `planned-commits.md`, `EXECUTION_PLAN.md`
- Modify: `PRD.md` (status line, §11 final paragraph), `SRS.md` (status line, §12 first bullet), `README.md` (project status)

- [ ] **Step 1:** Write `planned-commits.md` (commit schedule, budget, cut order) and this plan.
- [ ] **Step 2:** Record the professor's approval as reported by the student. Set the PRD and SRS status lines to `approved by the professor (reported by the student on 2026-09-30); implementation in progress`. Replace statements that approval is still pending with the date it was reported.
- [ ] **Step 3:** Check that `git diff --check` is clean, then commit:

```bash
git add planned-commits.md EXECUTION_PLAN.md PRD.md SRS.md README.md
git commit -m "Plan the incremental v0.2 build and daily commit schedule"
```

### Task 0.2: Project skeleton and configuration

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.gitignore`, `app/__init__.py`, `app/config.py`
- Create: `tests/__init__.py` (empty), `tests/test_config.py`

**Interfaces:**
- Produces: `Settings(port, data_dir, timezone, cookie_secure, session_idle_hours, session_max_days)` with `.db_path` and `.tz`; `load_settings(env=None, dotenv=Path(".env")) -> Settings`; `ConfigError`.

- [ ] **Step 1: Write the manifest, test configuration, and ignore rules**

```text
# file: requirements.txt
# Float's only dependency manifest (NFR-03): direct dependencies pinned to the tested versions.
fastapi==0.142.1
uvicorn==0.54.0
jinja2==3.1.6
python-multipart==0.0.32
pytest==9.1.1
pytest-cov==7.1.0
hypothesis==6.168.3
httpx2==2.13.1
```

```ini
# file: pytest.ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -ra --strict-markers
```

```text
# file: .gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
.hypothesis/
.coverage
.coverage.*
htmlcov/
data/
*.sqlite3
*.sqlite3-*
.env
.DS_Store
```

Then run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

- [ ] **Step 2: Write the failing configuration tests**

```python
# file: tests/test_config.py
from pathlib import Path

import pytest

from app.config import ConfigError, Settings, load_settings


def test_defaults_apply_without_environment_or_dotenv(tmp_path):
    settings = load_settings({}, dotenv=tmp_path / "missing.env")
    assert settings == Settings()
    assert settings.db_path == Path("data") / "float.sqlite3"
    assert settings.tz.key == "Europe/Madrid"


def test_reads_every_supported_variable(tmp_path):
    settings = load_settings(
        {
            "PORT": "9000",
            "DATA_DIR": str(tmp_path),
            "APP_TIMEZONE": "UTC",
            "COOKIE_SECURE": "true",
            "SESSION_IDLE_HOURS": "1",
            "SESSION_MAX_DAYS": "2",
        },
        dotenv=None,
    )
    assert settings == Settings(9000, tmp_path, "UTC", True, 1, 2)


def test_environment_overrides_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# local overrides\nPORT=7000\nAPP_TIMEZONE='UTC'\n", encoding="utf-8")
    assert load_settings({}, dotenv=dotenv).port == 7000
    assert load_settings({}, dotenv=dotenv).timezone == "UTC"
    assert load_settings({"PORT": "7100"}, dotenv=dotenv).port == 7100


@pytest.mark.parametrize(
    "env, variable",
    [
        ({"PORT": "abc"}, "PORT"),
        ({"PORT": "0"}, "PORT"),
        ({"PORT": "70000"}, "PORT"),
        ({"APP_TIMEZONE": "Mars/Base"}, "APP_TIMEZONE"),
        ({"COOKIE_SECURE": "maybe"}, "COOKIE_SECURE"),
        ({"SESSION_IDLE_HOURS": "0"}, "SESSION_IDLE_HOURS"),
        ({"SESSION_MAX_DAYS": "91"}, "SESSION_MAX_DAYS"),
    ],
)
def test_invalid_values_fail_with_the_variable_name(env, variable):
    with pytest.raises(ConfigError, match=variable):
        load_settings(env, dotenv=None)


def test_malformed_dotenv_line_is_reported(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("NOT A PAIR\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="line 1"):
        load_settings({}, dotenv=dotenv)
```

- [ ] **Step 3: Run it and watch it fail**

Run: `pytest tests/test_config.py -q`. Expected: collection error `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 4: Implement settings**

```python
# file: app/__init__.py
"""Float: a money co-pilot for students on an allowance who share a flat."""
```

```python
# file: app/config.py
"""Runtime configuration from environment variables and an optional .env file (NFR-06)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """A configuration value is invalid. The message names the variable."""


@dataclass(frozen=True)
class Settings:
    port: int = 8000
    data_dir: Path = Path("data")
    timezone: str = "Europe/Madrid"
    cookie_secure: bool = False
    session_idle_hours: int = 48
    session_max_days: int = 14

    @property
    def db_path(self) -> Path:
        return self.data_dir / "float.sqlite3"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and # comments. A missing file gives {}."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"{path.name} line {number}: expected KEY=VALUE")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _integer(values: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None
    if not low <= number <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {number}")
    return number


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


def load_settings(env: Mapping[str, str] | None = None, dotenv: Path | None = Path(".env")) -> Settings:
    """Read settings from ``env`` (default ``os.environ``), falling back to ``dotenv`` values."""
    values: dict[str, str] = read_dotenv(dotenv) if dotenv is not None else {}
    values.update(os.environ if env is None else env)
    timezone = values.get("APP_TIMEZONE", "").strip() or "Europe/Madrid"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"APP_TIMEZONE is not a known time zone: {timezone!r}") from None
    return Settings(
        port=_integer(values, "PORT", 8000, 1, 65535),
        data_dir=Path(values.get("DATA_DIR", "").strip() or "data"),
        timezone=timezone,
        cookie_secure=_boolean(values, "COOKIE_SECURE", False),
        session_idle_hours=_integer(values, "SESSION_IDLE_HOURS", 48, 1, 720),
        session_max_days=_integer(values, "SESSION_MAX_DAYS", 14, 1, 90),
    )
```

- [ ] **Step 5: Run it and watch it pass**

Run: `pytest tests/test_config.py -q`. Expected: `11 passed`.

### Task 0.3: SQLite connection, unit of work, and migrations

**Files:**
- Create: `app/db/__init__.py`, `app/db/connection.py`, `app/db/unit_of_work.py`, `app/db/migrations.py`, `app/db/migrations/0001_foundation.sql`
- Create: `tests/conftest.py` (database fixture only), `tests/db/__init__.py` (empty), `tests/db/test_migrations.py`, `tests/db/test_unit_of_work.py`

**Interfaces:**
- Produces: `connect(path) -> sqlite3.Connection` (autocommit mode, `sqlite3.Row` rows, pragmas set); `enable_wal(conn) -> str`; `transaction(conn)` context manager; `apply_migrations(conn, directory=MIGRATIONS_DIR) -> list[str]`; `initialize_database(db_path) -> list[str]`; table `categories(id, slug, name)` with IDs 1–11.

- [ ] **Step 1: Write the failing tests**

```python
# file: tests/conftest.py
"""Shared pytest fixtures. Every test gets its own temporary database."""

import pytest

from app.db.connection import connect
from app.db.migrations import apply_migrations


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    apply_migrations(connection)
    try:
        yield connection
    finally:
        connection.close()
```

```python
# file: tests/db/test_migrations.py
import sqlite3

import pytest

from app.db.connection import connect
from app.db.migrations import MIGRATIONS_DIR, apply_migrations, initialize_database

ALL_VERSIONS = sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))
EXPECTED_SLUGS = [
    "groceries", "eating_out", "transport", "housing", "utilities", "subscriptions",
    "study", "leisure", "health", "travel", "other",
]


def test_fixed_categories_are_seeded(conn):
    rows = conn.execute("SELECT slug FROM categories ORDER BY id").fetchall()
    assert [row["slug"] for row in rows] == EXPECTED_SLUGS


def test_categories_cannot_be_renamed_or_deleted(conn):
    with pytest.raises(sqlite3.IntegrityError, match="fixed"):
        conn.execute("UPDATE categories SET name = 'Food' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="fixed"):
        conn.execute("DELETE FROM categories WHERE id = 11")


def test_migrations_are_applied_once(conn):
    assert apply_migrations(conn) == []
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ALL_VERSIONS
    assert versions[0] == "0001_foundation"


def test_connection_enforces_foreign_keys_and_waits_for_locks(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_failed_migration_leaves_no_trace(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_good.sql").write_text("CREATE TABLE a (x INTEGER) STRICT;", encoding="utf-8")
    (directory / "0002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER) STRICT;\nINSERT INTO missing VALUES (1);", encoding="utf-8"
    )
    conn = connect(tmp_path / "db.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, directory)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "a" in tables and "b" not in tables
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations")] == ["0001_good"]
    assert not conn.in_transaction
    conn.close()


def test_unexpected_file_names_are_rejected(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "init.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = connect(tmp_path / "db.sqlite3")
    with pytest.raises(ValueError, match="init.sql"):
        apply_migrations(conn, directory)
    conn.close()


def test_initialize_database_creates_directory_and_enables_wal(tmp_path):
    db_path = tmp_path / "nested" / "float.sqlite3"
    assert initialize_database(db_path) == ALL_VERSIONS
    assert initialize_database(db_path) == []
    conn = connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
```

```python
# file: tests/db/test_unit_of_work.py
import sqlite3

import pytest

from app.db.connection import connect, enable_wal
from app.db.unit_of_work import transaction


@pytest.fixture
def table(conn):
    conn.execute("CREATE TABLE t (x INTEGER NOT NULL) STRICT")
    return conn


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def test_commits_when_the_block_succeeds(table):
    with transaction(table):
        table.execute("INSERT INTO t VALUES (1)")
    assert count(table) == 1
    assert not table.in_transaction


def test_rolls_back_every_write_when_the_block_fails(table):
    with pytest.raises(RuntimeError, match="boom"):
        with transaction(table):
            table.execute("INSERT INTO t VALUES (1)")
            table.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("boom")
    assert count(table) == 0
    assert not table.in_transaction


def test_nesting_is_rejected(table):
    with transaction(table):
        with pytest.raises(RuntimeError, match="nested"):
            with transaction(table):
                pass


def test_write_lock_is_taken_up_front(tmp_path):
    path = tmp_path / "lock.sqlite3"
    first, second = connect(path), connect(path)
    enable_wal(first)
    second.execute("PRAGMA busy_timeout = 0")
    try:
        with transaction(first):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second.execute("BEGIN IMMEDIATE")
    finally:
        first.close()
        second.close()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/db -q`. Expected: `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implement the database layer**

```python
# file: app/db/__init__.py
"""SQLite access: connections, transactions, and migrations (SRS §6.4, §7)."""
```

```python
# file: app/db/connection.py
"""SQLite connections with the pragmas Float requires on every connection (SRS §6.4)."""

import sqlite3
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection in autocommit mode; writes go through ``transaction()``.

    ``check_same_thread=False`` because FastAPI may run a request's dependency and its
    endpoint on different worker threads. Each connection still serves only one request.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def enable_wal(conn: sqlite3.Connection) -> str:
    """Switch the database file to write-ahead logging and return the resulting mode."""
    return conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
```

```python
# file: app/db/unit_of_work.py
"""One database transaction per write use case (SRS §6.4)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block between ``BEGIN IMMEDIATE`` and ``COMMIT``; roll back on any exception.

    IMMEDIATE takes the write lock up front, so two writers never deadlock while upgrading
    a read lock. Nesting is a bug: services receive the open connection instead.
    """
    if conn.in_transaction:
        raise RuntimeError("transaction() cannot be nested; pass the open connection instead")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
```

```python
# file: app/db/migrations.py
"""Numbered SQL migrations, each applied exactly once in its own transaction (NFR-02)."""

import re
import sqlite3
from pathlib import Path

from app.db.connection import connect, enable_wal

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_VERSION = re.compile(r"\d{4}_[a-z0-9_]+")


def apply_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration in ``directory`` that is not yet recorded; return their versions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL) STRICT"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        version = path.stem
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Unexpected migration file name: {path.name}")
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        # executescript() cannot take parameters or join an open transaction, so the
        # script carries its own BEGIN/COMMIT. `version` is a validated file name.
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\n;\n"
                "INSERT INTO schema_migrations (version, applied_at) "
                f"VALUES ('{version}', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));\n"
                "COMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def initialize_database(db_path: Path) -> list[str]:
    """Create the data directory and database file, enable WAL, and apply migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        enable_wal(conn)
        return apply_migrations(conn)
    finally:
        conn.close()
```

```sql
-- file: app/db/migrations/0001_foundation.sql
-- Fixed expense categories owned by the Ledger (FR-08). IDs are stable so tests can use them.
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE
) STRICT;

INSERT INTO categories (id, slug, name) VALUES
    (1, 'groceries', 'Groceries'),
    (2, 'eating_out', 'Eating out'),
    (3, 'transport', 'Transport'),
    (4, 'housing', 'Housing'),
    (5, 'utilities', 'Utilities'),
    (6, 'subscriptions', 'Subscriptions'),
    (7, 'study', 'Study'),
    (8, 'leisure', 'Leisure'),
    (9, 'health', 'Health'),
    (10, 'travel', 'Travel'),
    (11, 'other', 'Other');

CREATE TRIGGER categories_fixed_on_update BEFORE UPDATE ON categories
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;

CREATE TRIGGER categories_fixed_on_delete BEFORE DELETE ON categories
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pytest tests/db -q`. Expected: `11 passed`.

### Task 0.4: Clock, app factory, web shell, entry point, and dependency rule

**Files:**
- Create: `app/shared/__init__.py`, `app/shared/clock.py`, `app/main.py`, `app.py`
- Create: `app/web/__init__.py`, `app/web/templating.py`, `app/web/routes.py`, `app/web/templates/base.html`, `app/web/templates/home.html`, `app/web/static/float.css`
- Replace: `tests/conftest.py` (adds clock, settings, and client fixtures)
- Create: `tests/test_app.py`, `tests/test_architecture.py`, `tests/shared/__init__.py` (empty), `tests/shared/test_clock.py`

**Interfaces:**
- Consumes: `load_settings`, `Settings` (Task 0.2); `initialize_database` (Task 0.3).
- Produces: `Clock` protocol (`now_utc() -> datetime`, `today() -> date`); `SystemClock(tz)`; `FixedClock(now, tz)`, `FixedClock.on(day, tz)`, `.advance(**timedelta_kwargs)`; `to_utc_text(dt) -> str`; `from_utc_text(text) -> datetime`; `create_app(settings=None, clock=None) -> FastAPI` with `app.state.settings` and `app.state.clock`; `templates` (Jinja2Templates); `imported_modules(path, root)` in the architecture test.

- [ ] **Step 1: Write the failing tests**

```python
# file: tests/conftest.py
"""Shared pytest fixtures. Every test gets its own temporary database."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import connect
from app.db.migrations import apply_migrations
from app.main import create_app
from app.shared.clock import FixedClock

MADRID = ZoneInfo("Europe/Madrid")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 30, 10, 0, tzinfo=MADRID), MADRID)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings, clock):
    with TestClient(create_app(settings, clock)) as test_client:
        yield test_client


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    apply_migrations(connection)
    try:
        yield connection
    finally:
        connection.close()
```

```python
# file: tests/shared/test_clock.py
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.shared.clock import FixedClock, SystemClock, from_utc_text, to_utc_text

MADRID = ZoneInfo("Europe/Madrid")


def test_today_is_the_calendar_date_in_the_configured_zone():
    late_evening_utc = datetime(2026, 9, 30, 22, 30, tzinfo=UTC)  # 00:30 on 1 Oct in Madrid
    assert FixedClock(late_evening_utc, MADRID).today() == date(2026, 10, 1)
    assert FixedClock(late_evening_utc).today() == date(2026, 9, 30)


def test_fixed_clock_can_start_on_a_day_and_advance():
    clock = FixedClock.on(date(2026, 9, 20), MADRID)
    assert clock.today() == date(2026, 9, 20)
    clock.advance(days=11)
    assert clock.today() == date(2026, 10, 1)
    assert clock.now_utc().tzinfo is UTC


def test_fixed_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError, match="aware"):
        FixedClock(datetime(2026, 9, 30, 12, 0))


def test_system_clock_returns_aware_utc():
    assert SystemClock(MADRID).now_utc().tzinfo is UTC


def test_utc_text_round_trips_and_sorts():
    moment = datetime(2026, 9, 30, 8, 59, 54, 123456, tzinfo=UTC)
    text = to_utc_text(moment.astimezone(MADRID))
    assert text == "2026-09-30T08:59:54.123456Z"
    assert from_utc_text(text) == moment
    assert to_utc_text(datetime(2026, 10, 1, tzinfo=UTC)) > text
    with pytest.raises(ValueError, match="aware"):
        to_utc_text(datetime(2026, 9, 30))
```

```python
# file: tests/test_app.py
import importlib.util
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrations import MIGRATIONS_DIR
from app.main import create_app
from app.web.templating import templates

ROOT = Path(__file__).resolve().parents[1]


def load_entry_point():
    spec = importlib.util.spec_from_file_location("float_entry", ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_page_uses_the_injected_clock(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<h1>Float</h1>" in response.text
    assert "2026-09-30" in response.text
    assert "Europe/Madrid" in response.text


def test_stylesheet_is_served(client):
    response = client.get("/static/float.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_openapi_schema_is_published(client):
    assert client.get("/api/openapi.json").json()["info"]["title"] == "Float"


def test_templates_escape_user_text():
    rendered = templates.env.from_string("{{ note }}").render(note="<script>alert(1)</script>")
    assert rendered == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_startup_prepares_the_database_and_survives_restart(settings, clock):
    create_app(settings, clock)
    create_app(settings, clock)  # a restart applies nothing twice
    conn = connect(settings.db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        migrations = len(list(MIGRATIONS_DIR.glob("*.sql")))
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == migrations
        assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 11
    finally:
        conn.close()


def test_entry_point_runs_one_worker_without_reload(monkeypatch, tmp_path):
    entry = load_entry_point()
    calls = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **options: calls.update(options, app=app))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PORT", "8123")
    entry.main()
    assert (calls["host"], calls["port"], calls["workers"], calls["reload"]) == ("0.0.0.0", 8123, 1, False)
    assert (tmp_path / "data" / "float.sqlite3").exists()


def test_entry_point_rejects_invalid_configuration(monkeypatch, capsys):
    entry = load_entry_point()
    monkeypatch.setenv("PORT", "not-a-port")
    with pytest.raises(SystemExit) as exit_info:
        entry.main()
    assert exit_info.value.code == 2
    assert "PORT" in capsys.readouterr().err
```

```python
# file: tests/test_architecture.py
"""Enforce the dependency rule of SRS §6.1 by reading import statements."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DOMAINS = {"identity", "ledger", "planning", "households", "insights"}


def imported_modules(path: Path, root: Path = ROOT) -> set[str]:
    """Fully qualified names imported by ``path``, with relative imports resolved."""
    package_parts = list(path.relative_to(root).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def python_files(package: str) -> list[Path]:
    directory = APP / package
    return sorted(directory.rglob("*.py")) if directory.is_dir() else []


def test_domains_do_not_import_each_other():
    violations = []
    for domain in sorted(DOMAINS):
        for path in python_files(domain):
            for module in sorted(imported_modules(path)):
                parts = module.split(".")
                if len(parts) < 2 or parts[0] != "app" or parts[1] not in DOMAINS or parts[1] == domain:
                    continue
                if domain == "insights" and len(parts) >= 3 and parts[2] == "api":
                    continue
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_shared_kernel_has_no_io_or_domain_dependencies():
    forbidden = ("sqlite3", "fastapi", "starlette", "app.db", "app.web", "app.application", "app.api")
    forbidden += tuple(f"app.{domain}" for domain in DOMAINS)
    violations = [
        f"{path.relative_to(ROOT)} imports {module}"
        for path in python_files("shared")
        for module in sorted(imported_modules(path))
        if module.startswith(forbidden)
    ]
    assert violations == []


def test_checker_resolves_relative_and_absolute_imports(tmp_path):
    module = tmp_path / "app" / "ledger" / "service.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from ..planning import api\nfrom . import rules\nimport app.households.service\n",
        encoding="utf-8",
    )
    assert imported_modules(module, tmp_path) == {
        "app.planning.api",
        "app.ledger.rules",
        "app.households.service",
    }
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest -q`. Expected: collection errors, `No module named 'app.main'` and `No module named 'app.shared'`.

- [ ] **Step 3: Implement the clock**

```python
# file: app/shared/__init__.py
"""Pure building blocks shared by every domain: no I/O, no framework (SRS §6.1)."""
```

```python
# file: app/shared/clock.py
"""Injectable time, so every date-dependent rule can be tested (SRS §2, §6.4)."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol, Self
from zoneinfo import ZoneInfo

_UTC_TEXT = "%Y-%m-%dT%H:%M:%S.%fZ"


class Clock(Protocol):
    def now_utc(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    """Real time. ``today`` is the calendar date in the configured time zone."""

    def __init__(self, timezone: ZoneInfo) -> None:
        self._timezone = timezone

    def now_utc(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return datetime.now(self._timezone).date()


class FixedClock:
    """A controllable clock for tests."""

    def __init__(self, now: datetime, timezone: ZoneInfo | None = None) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = now.astimezone(UTC)
        self._timezone = timezone or ZoneInfo("UTC")

    @classmethod
    def on(cls, day: date, timezone: ZoneInfo | None = None) -> Self:
        """Noon on ``day`` in ``timezone``, far from midnight, so ``today()`` is ``day``."""
        zone = timezone or ZoneInfo("UTC")
        return cls(datetime(day.year, day.month, day.day, 12, tzinfo=zone), zone)

    def now_utc(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(self._timezone).date()

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


def to_utc_text(moment: datetime) -> str:
    """Sortable UTC text for timestamp columns, e.g. ``2026-09-30T08:59:54.123456Z``."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).strftime(_UTC_TEXT)


def from_utc_text(text: str) -> datetime:
    return datetime.strptime(text, _UTC_TEXT).replace(tzinfo=UTC)
```

- [ ] **Step 4: Implement the web shell, app factory, and entry point**

```python
# file: app/web/__init__.py
"""Server-rendered HTML interface (SRS §8.1)."""
```

```python
# file: app/web/templating.py
"""The Jinja2 environment shared by every HTML route. Autoescaping is on (SRS §9)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
```

```python
# file: app/web/routes.py
"""Routes that exist before any domain: the health check and the home page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check used by the README smoke test."""
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    today = request.app.state.clock.today()
    timezone = request.app.state.settings.timezone
    return templates.TemplateResponse(request, "home.html", {"today": today, "timezone": timezone})
```

```html
{# file: app/web/templates/base.html #}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Float{% endblock %} · Float</title>
  <link rel="stylesheet" href="{{ url_for('static', path='float.css') }}">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="/">Float</a>
    <nav aria-label="Main">{% block nav %}{% endblock %}</nav>
  </header>
  <main id="content" class="page">
    {% block content %}{% endblock %}
  </main>
  <footer class="site-footer">
    <p>Estimates depend on complete, accurate records. Float never connects to a bank.</p>
  </footer>
</body>
</html>
```

```html
{# file: app/web/templates/home.html #}
{% extends "base.html" %}
{% block title %}Welcome{% endblock %}
{% block content %}
  <h1>Float</h1>
  <p class="lead">What can I safely spend today, after my bills, my share of the flat, what I owe my flatmates, and my savings plan?</p>
  <p>The foundation is running. Accounts and setup arrive in the next build step.</p>
  <p class="muted">Today is <time datetime="{{ today.isoformat() }}">{{ today.isoformat() }}</time> ({{ timezone }}).</p>
{% endblock %}
```

```css
/* file: app/web/static/float.css */
:root {
  color-scheme: light dark;
  --bg: #f7f7f5;
  --surface: #ffffff;
  --text: #1d1f23;
  --muted: #5d636d;
  --accent: #1f6f5c;
  --danger: #a3261f;
  --warning: #8a5a00;
  --border: #d9dcd6;
  --radius: 10px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  line-height: 1.5;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a;
    --surface: #1e2125;
    --text: #eceef0;
    --muted: #a3a9b2;
    --accent: #5cc7a8;
    --danger: #ff8a80;
    --warning: #ffc76b;
    --border: #33373d;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
}

.site-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.brand {
  color: var(--accent);
  font-size: 1.25rem;
  font-weight: 700;
  text-decoration: none;
}

nav a { margin-left: 0.75rem; color: var(--text); }

.page {
  max-width: 48rem;
  margin: 0 auto;
  padding: 1rem;
}

.lead { font-size: 1.15rem; }

.muted,
.site-footer { color: var(--muted); }

.site-footer {
  max-width: 48rem;
  margin: 2rem auto;
  padding: 0 1rem;
  font-size: 0.875rem;
}

a:focus-visible,
button:focus-visible,
input:focus-visible,
select:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
}
```

```python
# file: app/main.py
"""Application factory: one process serving HTML and static files (NFR-01)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, load_settings
from app.db.migrations import initialize_database
from app.shared.clock import Clock, SystemClock
from app.web.routes import router as web_router

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    """Build the app. Database setup runs here, so a bad path or migration fails at startup."""
    settings = settings or load_settings()
    initialize_database(settings.db_path)
    app = FastAPI(
        title="Float",
        version="0.2.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock(settings.tz)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web_router)
    return app
```

```python
# file: app.py
"""Start Float with `python app.py` (NFR-01). Configuration comes from the environment or .env."""

import sys

import uvicorn

from app.config import ConfigError, load_settings
from app.main import create_app


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Float configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

The package `app/` and the script `app.py` share a name on purpose: the SRS fixes the start command as `python app.py`. When a directory package and a module have the same name, Python's import system resolves `import app` to the package, so `from app.config import …` inside `app.py` works.

- [ ] **Step 5: Run everything and watch it pass**

Run: `pytest -q`. Expected: all tests pass (`38 passed`) with no warnings. Then smoke-test the real server with `DATA_DIR=$(mktemp -d) PORT=8765 python app.py`, run `curl -s localhost:8765/healthz` in a second shell (expected `{"status":"ok"}`), and stop the server.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini .gitignore app.py app tests
git commit -m "Add FastAPI skeleton with configuration and SQLite migrations"
```

### Task 0.5: Domain errors and exact money

**Files:**
- Create: `app/shared/errors.py`, `app/shared/money.py`, `tests/shared/test_errors.py`, `tests/shared/test_money.py`
- Replace: `app/web/templating.py` (registers the `money` filter)

**Interfaces:**
- Produces: `FloatError`, `ValidationError(errors: Mapping[str, str])` with `.errors` and `ValidationError.single(field, message)`, `NotFoundError`, `PermissionDeniedError`, `ConflictError`; `MAX_CENTS = 100_000_000`; `parse_money(text, *, field="amount", allow_zero=False, allow_negative=False) -> int`; `format_money(cents) -> str`; `cents_to_input(cents) -> str`; the Jinja filter `{{ cents|money }}`.

- [ ] **Step 1: Write the failing tests**

```python
# file: tests/shared/test_errors.py
import pytest

from app.shared.errors import ValidationError


def test_validation_error_keeps_every_field_message():
    error = ValidationError({"amount": "Enter an amount.", "date": "Enter a date as YYYY-MM-DD."})
    assert error.errors == {"amount": "Enter an amount.", "date": "Enter a date as YYYY-MM-DD."}
    assert "amount: Enter an amount." in str(error)


def test_single_field_shortcut():
    assert ValidationError.single("amount", "Enter an amount.").errors == {"amount": "Enter an amount."}


def test_an_empty_validation_error_is_a_programming_mistake():
    with pytest.raises(ValueError):
        ValidationError({})
```

```python
# file: tests/shared/test_money.py
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS, cents_to_input, format_money, parse_money
from app.web.templating import templates


@pytest.mark.parametrize(
    "text, cents",
    [
        ("12", 1200),
        ("12.5", 1250),
        ("12.50", 1250),
        ("12,50", 1250),
        ("0.01", 1),
        ("25.40", 2540),
        (" 7 ", 700),
        ("€7", 700),
        ("€ 1 234,56", 123456),
        ("1000000.00", MAX_CENTS),
    ],
)
def test_parses_exact_cents(text, cents):
    assert parse_money(text) == cents


@pytest.mark.parametrize(
    "text, message",
    [
        (None, "Enter an amount."),
        ("", "Enter an amount."),
        ("abc", "Enter an amount like 12.50."),
        ("12.", "Enter an amount like 12.50."),
        (".5", "Enter an amount like 12.50."),
        ("1.000.000", "Enter an amount like 12.50."),
        ("1.234", "Use at most two decimal places."),
        ("1,234", "Use at most two decimal places."),
        ("0", "Enter an amount greater than zero."),
        ("-5", "Enter a positive amount."),
        ("1000000.01", "Amounts are limited to €1,000,000.00."),
    ],
)
def test_rejects_invalid_input_with_a_clear_message(text, message):
    with pytest.raises(ValidationError) as error:
        parse_money(text, field="amount")
    assert error.value.errors == {"amount": message}


def test_zero_and_negative_amounts_are_opt_in():
    assert parse_money("0", allow_zero=True) == 0
    assert parse_money("-12.30", allow_negative=True) == -1230
    assert parse_money("−4", allow_negative=True) == -400  # typographic minus sign
    assert parse_money("-1000000", allow_negative=True) == -MAX_CENTS


def test_formats_amounts_for_display():
    assert format_money(0) == "€0.00"
    assert format_money(5) == "€0.05"
    assert format_money(123456) == "€1,234.56"
    assert format_money(-500) == "-€5.00"
    assert format_money(MAX_CENTS) == "€1,000,000.00"


def test_money_filter_is_available_in_templates():
    assert templates.env.from_string("{{ 123456|money }}").render() == "€1,234.56"


@given(st.integers(min_value=-MAX_CENTS, max_value=MAX_CENTS))
def test_form_values_round_trip_exactly(cents):
    assert parse_money(cents_to_input(cents), allow_zero=True, allow_negative=True) == cents
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/shared/test_errors.py tests/shared/test_money.py -q`. Expected: `No module named 'app.shared.errors'`.

- [ ] **Step 3: Implement errors, money, and the template filter**

```python
# file: app/shared/errors.py
"""Expected, user-facing errors raised by rules and services; the web layer maps them to HTTP codes."""

from collections.abc import Mapping
from typing import Self


class FloatError(Exception):
    """An error caused by the request or the data, not a bug in Float."""


class ValidationError(FloatError):
    """One or more fields are invalid. ``errors`` maps each field name to a message."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        if not errors:
            raise ValueError("ValidationError needs at least one field error")
        self.errors: dict[str, str] = dict(errors)
        super().__init__("; ".join(f"{field}: {message}" for field, message in self.errors.items()))

    @classmethod
    def single(cls, field: str, message: str) -> Self:
        return cls({field: message})


class NotFoundError(FloatError):
    """The record does not exist, or it belongs to someone else (FR-04 answers 404 for both)."""


class PermissionDeniedError(FloatError):
    """The caller is a household member but lacks the role for this action (403)."""


class ConflictError(FloatError):
    """The record changed since it was read, or the action no longer applies (409)."""
```

```python
# file: app/shared/money.py
"""Exact euro amounts as integer cents (SRS §2). Never use float for money."""

import re

from app.shared.errors import ValidationError

MAX_CENTS = 100_000_000  # €1,000,000.00, the largest magnitude Float accepts
_AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:[.,]([0-9]+))?")


def parse_money(
    text: str | None,
    *,
    field: str = "amount",
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> int:
    """Parse input such as ``12.5``, ``12,50``, ``€ 7`` or ``1 234,56`` into integer cents.

    One decimal separator (``.`` or ``,``) followed by at most two digits is accepted.
    Anything else is rejected rather than rounded or guessed: ``1,234`` is an error, not 1234.
    """
    cleaned = "" if text is None else str(text)
    for symbol in ("€", " ", " "):
        cleaned = cleaned.replace(symbol, "")
    cleaned = cleaned.replace("−", "-")
    if not cleaned:
        raise ValidationError.single(field, "Enter an amount.")
    match = _AMOUNT.fullmatch(cleaned)
    if match is None:
        raise ValidationError.single(field, "Enter an amount like 12.50.")
    sign, whole, fraction = match.groups()
    fraction = fraction or ""
    if len(fraction) > 2:
        raise ValidationError.single(field, "Use at most two decimal places.")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if sign == "-":
        cents = -cents
    if abs(cents) > MAX_CENTS:
        raise ValidationError.single(field, "Amounts are limited to €1,000,000.00.")
    if cents < 0 and not allow_negative:
        raise ValidationError.single(field, "Enter a positive amount.")
    if cents == 0 and not allow_zero:
        raise ValidationError.single(field, "Enter an amount greater than zero.")
    return cents


def format_money(cents: int) -> str:
    """Display format: ``123456`` → ``€1,234.56`` and ``-500`` → ``-€5.00``."""
    sign = "-" if cents < 0 else ""
    euros, remainder = divmod(abs(cents), 100)
    return f"{sign}€{euros:,}.{remainder:02d}"


def cents_to_input(cents: int) -> str:
    """Form-field format that ``parse_money`` reads back exactly: ``123456`` → ``1234.56``."""
    sign = "-" if cents < 0 else ""
    euros, remainder = divmod(abs(cents), 100)
    return f"{sign}{euros}.{remainder:02d}"
```

```python
# file: app/web/templating.py
"""The Jinja2 environment shared by every HTML route. Autoescaping is on (SRS §9)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.shared.money import format_money

TEMPLATES_DIR = Path(__file__).with_name("templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = format_money
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pytest tests/shared -q`. Expected: all pass, including 100 Hypothesis examples of the round trip.

### Task 0.6: Allowance-cycle dates

**Files:**
- Create: `app/shared/dates.py`, `tests/shared/test_dates.py`

**Interfaces:**
- Consumes: `ValidationError` (Task 0.5).
- Produces: `last_day_of_month(year, month) -> int`; `add_months(year, month, months) -> tuple[int, int]`; `scheduled_date(year, month, day) -> date`; `validate_allowance_day(day) -> int`; `Cycle(today, start, next_allowance, horizon_end)` with `.days_remaining`; `cycle_for(today, allowance_day) -> Cycle`; `allowance_dates(start, end_exclusive, allowance_day) -> list[date]`; `parse_iso_date(text, *, field="date") -> date`.

- [ ] **Step 1: Write the failing tests** (Fixture A, AT-06, and cycle properties)

```python
# file: tests/shared/test_dates.py
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.dates import (
    Cycle,
    add_months,
    allowance_dates,
    cycle_for,
    parse_iso_date,
    scheduled_date,
)
from app.shared.errors import ValidationError


def test_fixture_a_cycle():
    cycle = cycle_for(date(2026, 9, 20), 1)
    assert cycle == Cycle(
        today=date(2026, 9, 20),
        start=date(2026, 9, 1),
        next_allowance=date(2026, 10, 1),
        horizon_end=date(2026, 11, 1),
    )
    assert cycle.days_remaining == 11


@pytest.mark.parametrize(
    "today, day, start, next_allowance, horizon_end",
    [
        (date(2027, 1, 31), 31, date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)),
        (date(2028, 1, 31), 31, date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)),
        (date(2027, 2, 28), 31, date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)),
        (date(2027, 3, 1), 31, date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)),
        (date(2026, 10, 1), 1, date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)),
        (date(2026, 12, 15), 20, date(2026, 11, 20), date(2026, 12, 20), date(2027, 1, 20)),
    ],
)
def test_cycle_boundaries(today, day, start, next_allowance, horizon_end):
    cycle = cycle_for(today, day)
    assert (cycle.start, cycle.next_allowance, cycle.horizon_end) == (start, next_allowance, horizon_end)


def test_payday_starts_a_new_cycle_and_never_divides_by_zero():
    assert cycle_for(date(2026, 10, 1), 1).days_remaining == 31


def test_scheduled_date_clamps_to_the_last_day_of_the_month():
    assert scheduled_date(2027, 2, 31) == date(2027, 2, 28)
    assert scheduled_date(2028, 2, 30) == date(2028, 2, 29)
    assert scheduled_date(2026, 4, 31) == date(2026, 4, 30)


def test_add_months_carries_the_year():
    assert add_months(2026, 11, 3) == (2027, 2)
    assert add_months(2027, 1, -1) == (2026, 12)
    assert add_months(2026, 9, 0) == (2026, 9)


def test_fixture_b_counts_six_cycles_before_march():
    assert allowance_dates(date(2026, 9, 1), date(2027, 3, 1), 1) == [
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1),
        date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1),
    ]


@pytest.mark.parametrize("day", [0, 32, -1])
def test_rejects_an_invalid_allowance_day(day):
    with pytest.raises(ValidationError) as error:
        cycle_for(date(2026, 9, 20), day)
    assert "allowance_day" in error.value.errors


def test_parses_strict_iso_dates():
    assert parse_iso_date("2026-09-30") == date(2026, 9, 30)
    assert parse_iso_date(" 2026-09-30 ") == date(2026, 9, 30)


@pytest.mark.parametrize("text", [None, "", "30/09/2026", "2026-W40-3", "20260930", "2026-02-30", "2026-9-3"])
def test_rejects_other_date_formats(text):
    with pytest.raises(ValidationError) as error:
        parse_iso_date(text, field="occurred_on")
    assert error.value.errors == {"occurred_on": "Enter a date as YYYY-MM-DD."}


@given(
    today=st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    day=st.integers(min_value=1, max_value=31),
)
def test_cycle_properties(today, day):
    cycle = cycle_for(today, day)
    assert cycle.start <= today < cycle.next_allowance < cycle.horizon_end
    assert cycle.days_remaining >= 1
    assert allowance_dates(cycle.start, cycle.horizon_end, day) == [cycle.start, cycle.next_allowance]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/shared/test_dates.py -q`. Expected: `No module named 'app.shared.dates'`.

- [ ] **Step 3: Implement cycle dates**

```python
# file: app/shared/dates.py
"""Calendar rules for allowance cycles (SRS §4.1)."""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.shared.errors import ValidationError

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(year: int, month: int, months: int) -> tuple[int, int]:
    """Move a (year, month) pair by ``months`` (may be negative), carrying the year."""
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def scheduled_date(year: int, month: int, day: int) -> date:
    """Day ``day`` of the month, clamped to the month's last day (31 → 28 February)."""
    return date(year, month, min(day, last_day_of_month(year, month)))


def validate_allowance_day(day: int) -> int:
    if not 1 <= day <= 31:
        raise ValidationError.single("allowance_day", "Choose a day between 1 and 31.")
    return day


@dataclass(frozen=True)
class Cycle:
    """The allowance cycle containing ``today`` (SRS §4.1)."""

    today: date
    start: date  # latest scheduled allowance date on or before today
    next_allowance: date  # earliest scheduled allowance date after today
    horizon_end: date  # the scheduled date after next_allowance; exclusive end of the horizon

    @property
    def days_remaining(self) -> int:
        return (self.next_allowance - self.today).days


def cycle_for(today: date, allowance_day: int) -> Cycle:
    validate_allowance_day(allowance_day)
    this_month = scheduled_date(today.year, today.month, allowance_day)
    if this_month <= today:
        start = this_month
        next_allowance = scheduled_date(*add_months(today.year, today.month, 1), allowance_day)
    else:
        start = scheduled_date(*add_months(today.year, today.month, -1), allowance_day)
        next_allowance = this_month
    horizon_end = scheduled_date(*add_months(next_allowance.year, next_allowance.month, 1), allowance_day)
    return Cycle(today=today, start=start, next_allowance=next_allowance, horizon_end=horizon_end)


def allowance_dates(start: date, end_exclusive: date, allowance_day: int) -> list[date]:
    """Every scheduled allowance date ``d`` with ``start <= d < end_exclusive``, in order."""
    validate_allowance_day(allowance_day)
    dates: list[date] = []
    year, month = start.year, start.month
    while (candidate := scheduled_date(year, month, allowance_day)) < end_exclusive:
        if candidate >= start:
            dates.append(candidate)
        year, month = add_months(year, month, 1)
    return dates


def parse_iso_date(text: str | None, *, field: str = "date") -> date:
    """Parse exactly ``YYYY-MM-DD``; other ISO forms (week dates, compact dates) are rejected."""
    raw = (text or "").strip()
    try:
        if not _ISO_DATE.fullmatch(raw):
            raise ValueError(raw)
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError.single(field, "Enter a date as YYYY-MM-DD.") from None
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pytest tests/shared/test_dates.py -q`. Expected: all pass.

### Task 0.7: Recurrence expansion

**Files:**
- Create: `app/shared/recurrence.py`, `tests/shared/test_recurrence.py`

**Interfaces:**
- Consumes: `add_months`, `scheduled_date`, `last_day_of_month` (Task 0.6); `ValidationError`.
- Produces: `FREQUENCIES`, `MAX_INTERVAL`, `MAX_COUNT = 500`; `Rule(freq, interval, anchor, until=None, count=None)`, which validates on construction; `candidate(rule, k) -> date`; `expand(rule, window_start, window_end_exclusive) -> list[date]`; `count_before(rule, day) -> int`. Planning (day 2) and Households (day 3) both materialize from `expand`.

- [ ] **Step 1: Write the failing tests** (Fixture E plus properties)

```python
# file: tests/shared/test_recurrence.py
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.dates import last_day_of_month
from app.shared.errors import ValidationError
from app.shared.recurrence import Rule, candidate, count_before, expand

D = date


def test_fixture_e_monthly_keeps_the_anchor_day_without_drift():
    rule = Rule("monthly", 1, D(2027, 1, 31))
    assert expand(rule, D(2027, 1, 1), D(2027, 5, 1)) == [
        D(2027, 1, 31), D(2027, 2, 28), D(2027, 3, 31), D(2027, 4, 30),
    ]


def test_fixture_e_leap_year():
    assert expand(Rule("monthly", 1, D(2028, 1, 31)), D(2028, 2, 1), D(2028, 3, 1)) == [D(2028, 2, 29)]


def test_fixture_e_every_two_weeks():
    assert D(2026, 9, 4).strftime("%A") == "Friday"
    assert expand(Rule("weekly", 2, D(2026, 9, 4)), D(2026, 9, 1), D(2026, 10, 20)) == [
        D(2026, 9, 4), D(2026, 9, 18), D(2026, 10, 2), D(2026, 10, 16),
    ]


def test_fixture_e_every_three_months():
    assert expand(Rule("monthly", 3, D(2026, 10, 15)), D(2026, 10, 1), D(2027, 5, 1)) == [
        D(2026, 10, 15), D(2027, 1, 15), D(2027, 4, 15),
    ]


def test_fixture_e_count_is_measured_from_the_anchor():
    rule = Rule("monthly", 1, D(2026, 11, 5), count=3)
    assert expand(rule, D(2026, 12, 1), D(2027, 12, 1)) == [D(2026, 12, 5), D(2027, 1, 5)]


def test_until_is_inclusive_and_window_end_is_exclusive():
    weekly = Rule("weekly", 1, D(2026, 9, 4), until=D(2026, 9, 18))
    assert expand(weekly, D(2026, 9, 1), D(2026, 12, 1)) == [D(2026, 9, 4), D(2026, 9, 11), D(2026, 9, 18)]
    monthly = Rule("monthly", 1, D(2026, 9, 25))
    assert expand(monthly, D(2026, 9, 1), D(2026, 10, 25)) == [D(2026, 9, 25)]


def test_once_produces_only_its_anchor():
    rule = Rule("once", 1, D(2026, 9, 25))
    assert expand(rule, D(2026, 9, 1), D(2027, 1, 1)) == [D(2026, 9, 25)]
    assert expand(rule, D(2026, 9, 26), D(2027, 1, 1)) == []


def test_a_window_starting_on_an_occurrence_includes_it():
    fortnightly = Rule("weekly", 2, D(2026, 9, 4))
    assert expand(fortnightly, D(2026, 9, 18), D(2026, 10, 3)) == [D(2026, 9, 18), D(2026, 10, 2)]
    gym = Rule("monthly", 1, D(2026, 7, 5))
    assert expand(gym, D(2026, 9, 5), D(2026, 10, 6)) == [D(2026, 9, 5), D(2026, 10, 5)]


def test_count_before_counts_valid_occurrences():
    gym = Rule("monthly", 1, D(2026, 7, 5))
    assert count_before(gym, D(2026, 10, 5)) == 3
    assert count_before(gym, D(2026, 7, 5)) == 0
    assert count_before(Rule("monthly", 1, D(2026, 7, 5), count=2), D(2027, 1, 1)) == 2


@pytest.mark.parametrize(
    "fields, bad_field",
    [
        ({"freq": "daily", "interval": 1}, "freq"),
        ({"freq": "weekly", "interval": 0}, "interval"),
        ({"freq": "weekly", "interval": 53}, "interval"),
        ({"freq": "monthly", "interval": 13}, "interval"),
        ({"freq": "once", "interval": 2}, "interval"),
        ({"freq": "monthly", "interval": 1, "until": D(2026, 12, 1), "count": 3}, "until"),
        ({"freq": "once", "interval": 1, "count": 1}, "until"),
        ({"freq": "monthly", "interval": 1, "until": D(2026, 8, 31)}, "until"),
        ({"freq": "monthly", "interval": 1, "count": 0}, "count"),
        ({"freq": "monthly", "interval": 1, "count": 501}, "count"),
    ],
)
def test_invalid_rules_are_rejected(fields, bad_field):
    with pytest.raises(ValidationError) as error:
        Rule(anchor=D(2026, 9, 1), **fields)
    assert bad_field in error.value.errors


@st.composite
def rules(draw):
    freq = draw(st.sampled_from(["once", "weekly", "monthly"]))
    interval = 1 if freq == "once" else draw(st.integers(1, 52 if freq == "weekly" else 12))
    anchor = draw(st.dates(D(2020, 1, 1), D(2030, 12, 31)))
    ending = "none" if freq == "once" else draw(st.sampled_from(["none", "until", "count"]))
    until = draw(st.dates(anchor, D(2035, 12, 31))) if ending == "until" else None
    count = draw(st.integers(1, 40)) if ending == "count" else None
    return Rule(freq, interval, anchor, until, count)


starts = st.dates(D(2019, 1, 1), D(2036, 1, 1))


@given(rules(), starts, st.integers(0, 800))
def test_results_are_sorted_unique_and_inside_the_window(rule, start, length):
    end = start + timedelta(days=length)
    result = expand(rule, start, end)
    assert result == sorted(set(result))
    assert all(start <= day < end for day in result)
    if rule.until is not None:
        assert all(day <= rule.until for day in result)


@given(rules(), starts, st.integers(0, 400), st.integers(0, 400))
def test_adjacent_windows_concatenate(rule, start, first, second):
    middle = start + timedelta(days=first)
    end = middle + timedelta(days=second)
    assert expand(rule, start, end) == expand(rule, start, middle) + expand(rule, middle, end)


@given(rules())
def test_occurrences_are_the_rule_candidates_in_order(rule):
    dates = expand(rule, rule.anchor, rule.anchor + timedelta(days=3 * 366))
    assert dates == [candidate(rule, k) for k in range(len(dates))]
    if rule.freq == "monthly":
        assert all(day.day == min(rule.anchor.day, last_day_of_month(day.year, day.month)) for day in dates)


@given(rules(), st.integers(0, 30))
def test_every_occurrence_is_found_by_a_window_starting_on_it(rule, k):
    occurrences = expand(rule, rule.anchor, rule.anchor + timedelta(days=3 * 366))
    if k < len(occurrences):
        day = occurrences[k]
        assert expand(rule, day, day + timedelta(days=1)) == [day]


@given(rules())
def test_count_limits_the_total_number_of_occurrences(rule):
    everything = expand(rule, rule.anchor, rule.anchor + timedelta(days=45 * 366))
    if rule.count is not None:
        assert len(everything) == rule.count
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pytest tests/shared/test_recurrence.py -q`. Expected: `No module named 'app.shared.recurrence'`.

- [ ] **Step 3: Implement the recurrence rules**

```python
# file: app/shared/recurrence.py
"""Recurrence rules for bills (SRS §4.2). Pure functions with no I/O."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.shared.dates import add_months, scheduled_date
from app.shared.errors import ValidationError

FREQUENCIES = ("once", "weekly", "monthly")
MAX_INTERVAL = {"once": 1, "weekly": 52, "monthly": 12}
MAX_COUNT = 500


@dataclass(frozen=True)
class Rule:
    """``freq`` every ``interval`` periods from ``anchor``, ending by ``until`` or ``count``."""

    freq: str
    interval: int
    anchor: date
    until: date | None = None
    count: int | None = None

    def __post_init__(self) -> None:
        errors: dict[str, str] = {}
        if self.freq not in FREQUENCIES:
            errors["freq"] = "Choose once, weekly, or monthly."
        elif not 1 <= self.interval <= MAX_INTERVAL[self.freq]:
            errors["interval"] = (
                "A one-off bill has no repeat interval."
                if self.freq == "once"
                else f"Choose an interval between 1 and {MAX_INTERVAL[self.freq]}."
            )
        if self.until is not None and self.count is not None:
            errors["until"] = "Choose an end date or a number of occurrences, not both."
        elif self.freq == "once" and (self.until is not None or self.count is not None):
            errors["until"] = "A one-off bill cannot have an end condition."
        elif self.until is not None and self.until < self.anchor:
            errors["until"] = "The end date cannot be before the first date."
        if self.count is not None and not 1 <= self.count <= MAX_COUNT:
            errors["count"] = f"Choose between 1 and {MAX_COUNT} occurrences."
        if errors:
            raise ValidationError(errors)


def candidate(rule: Rule, k: int) -> date:
    """The k-th date of the rule, ignoring end conditions; k = 0 is the anchor."""
    if rule.freq == "weekly":
        return rule.anchor + timedelta(weeks=rule.interval * k)
    if rule.freq == "monthly":
        year, month = add_months(rule.anchor.year, rule.anchor.month, rule.interval * k)
        return scheduled_date(year, month, rule.anchor.day)
    return rule.anchor


def _first_index_at_or_before(rule: Rule, day: date) -> int:
    """A k whose candidate is not after ``day`` (0 if ``day`` precedes the anchor), to skip ahead."""
    if day <= rule.anchor or rule.freq == "once":
        return 0
    if rule.freq == "weekly":
        return (day - rule.anchor).days // (7 * rule.interval)
    months = (day.year - rule.anchor.year) * 12 + (day.month - rule.anchor.month)
    return max(0, months // rule.interval - 1)


def expand(rule: Rule, window_start: date, window_end_exclusive: date) -> list[date]:
    """Valid occurrence dates ``d`` with ``window_start <= d < window_end_exclusive``, ascending.

    Candidates are counted from the anchor, so a count-limited rule yields the same dates
    whichever window is requested.
    """
    dates: list[date] = []
    k = _first_index_at_or_before(rule, window_start)
    while not (rule.freq == "once" and k > 0) and (rule.count is None or k < rule.count):
        current = candidate(rule, k)
        if (rule.until is not None and current > rule.until) or current >= window_end_exclusive:
            break
        if current >= window_start:
            dates.append(current)
        k += 1
    return dates


def count_before(rule: Rule, day: date) -> int:
    """How many valid occurrences fall strictly before ``day``."""
    return len(expand(rule, rule.anchor, day))
```

- [ ] **Step 4: Run them and watch them pass**

Run: `pytest tests/shared -q`. Expected: all pass. The Hypothesis properties run 100 examples each.

### Task 0.8: Documentation, verification, and delivery

**Files:**
- Modify: `README.md` (run instructions and today's measured test and coverage results), `AI_USAGE.md` (rows for today), `planned-commits.md` (tick boxes)

- [ ] **Step 1:** Add a **Running Float** section to the README covering: Python 3.12+, `python3 -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`, `python app.py`, then open `http://localhost:8000`. Add the test command `pytest` and the current coverage command `pytest --cov=app.shared --cov=app.db --cov-report=term-missing`. Record only numbers you actually measured.
- [ ] **Step 2:** Add today's `AI_USAGE.md` rows: the build-approach discussion and plan (Accepted: incremental daily build), and the foundation build. Mark explanations as AI-authored drafts pending the student's own words, and name the real functions (`parse_money`, `cycle_for`, `expand`).
- [ ] **Step 3: Verify.** Run `pytest -q`, the coverage command, `git diff --check`, and the `python app.py` smoke test from Task 0.4 Step 5. Everything must pass before committing.
- [ ] **Step 4: Commit, push, open the PR, and merge**

```bash
git add app tests README.md AI_USAGE.md planned-commits.md
git commit -m "Add exact money, allowance-cycle, and recurrence rules"
git push -u origin build/2026-09-30-foundation
gh pr create --base main --title "Build the Float foundation" --body "<summary, verification output, not-yet-implemented list>"
gh pr merge --merge
```

---

## Day 1 — Thursday 1 October: Identity and Ledger (P0)

**Deliverable:** people can register, log in, and log out with secure sessions. They complete setup and record, edit, and delete manual income and expenses. A dashboard shows their recorded balance, the current cycle, and the allowance reminder. Every mutation is protected by CSRF and written to an append-only audit trail. Covers FR-01–08, FR-28, FR-33 (table and writes), FR-39, NFR-10, and part of SRS §9. Tests: AT-01, AT-02, AT-04, AT-05, AT-21, AT-25 (append-only), and the first rows of the AT-03 authorization matrix.

### Task 1.1: Identity domain (FR-01–03)

**Files:**
- Create: `app/db/migrations/0002_identity.sql`
- Create: `app/identity/__init__.py`, `app/identity/rules.py`, `app/identity/repository.py`, `app/identity/service.py`, `app/identity/api.py`
- Create: `tests/identity/__init__.py`, `tests/identity/test_rules.py`, `tests/identity/test_service.py`

**Interfaces:**
- Consumes: `transaction`, `to_utc_text`/`from_utc_text`, `ValidationError`, `FloatError`.
- Produces (re-exported by `app/identity/api.py`):
  - `User(id: int, username: str, display_name: str)`; `Session(id: int, user: User, csrf_token: str)`
  - `AuthenticationError(FloatError)` with the fixed message "Incorrect username or password."
  - `LockedOutError(FloatError)` with "Too many attempts. Try again in 15 minutes."
  - `register(conn, *, username, display_name, password, now) -> User`
  - `login(conn, *, username, password, client_address, now, max_age) -> tuple[Session, str]`, returning the session and the raw token for the cookie
  - `resolve_session(conn, *, token, now, idle, max_age) -> Session | None`
  - `logout(conn, *, token) -> None`
  - `change_password(conn, *, user_id, current_password, new_password, keep_session_id, now) -> None`
  - `get_user(conn, user_id) -> User`

- [ ] **Step 1: Migration**

```sql
-- file: app/db/migrations/0002_identity.sql
-- Identity: accounts, server-side sessions, and login throttling (FR-01–03).
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE
        CHECK (length(username) BETWEEN 3 AND 32 AND username NOT GLOB '*[^a-z0-9_]*'),
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 50),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
    created_at TEXT NOT NULL,
    password_changed_at TEXT NOT NULL
) STRICT;

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) STRICT;
CREATE INDEX sessions_by_user ON sessions (user_id);

CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY,
    username_key TEXT NOT NULL,
    client_address TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1))
) STRICT;
CREATE INDEX login_attempts_by_username ON login_attempts (username_key, attempted_at);
CREATE INDEX login_attempts_by_address ON login_attempts (client_address, attempted_at);
```

- [ ] **Step 2: Failing rule tests** (`tests/identity/test_rules.py`)

```python
import pytest
from datetime import UTC, datetime, timedelta

from app.identity.rules import (
    hash_password, hash_token, is_locked, new_token, normalize_username,
    validate_display_name, validate_password, verify_password,
)
from app.shared.errors import ValidationError

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("raw, expected", [("Ana_1", "ana_1"), ("  ben ", "ben"), ("abc", "abc"), ("a" * 32, "a" * 32)])
def test_usernames_are_normalized(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "ab", "a" * 33, "ana!", "ana maria", "ána"])
def test_invalid_usernames_are_rejected(raw):
    with pytest.raises(ValidationError) as error:
        normalize_username(raw)
    assert "username" in error.value.errors


@pytest.mark.parametrize("raw, ok", [("x" * 9, False), ("x" * 10, True), ("x" * 128, True), ("x" * 129, False), (None, False)])
def test_password_length_rules(raw, ok):
    if ok:
        assert validate_password(raw) == raw
    else:
        with pytest.raises(ValidationError):
            validate_password(raw)


def test_display_name_is_trimmed_and_bounded():
    assert validate_display_name("  Ana  ") == "Ana"
    for bad in (None, "", " ", "x" * 51):
        with pytest.raises(ValidationError):
            validate_display_name(bad)


def test_scrypt_hash_verifies_and_is_salted():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("scrypt$16384$8$1$") and first != second
    assert verify_password("correct horse", first)
    assert not verify_password("wrong horse", first)
    assert not verify_password("correct horse", "scrypt$broken")


def test_tokens_are_random_and_stored_as_sha256():
    token = new_token()
    assert len(token) >= 43 and token != new_token()
    assert len(hash_token(token)) == 64 and hash_token(token) != token


def test_lockout_counts_failures_inside_the_window_only():
    recent = [NOW - timedelta(minutes=m) for m in range(4)]
    assert not is_locked(recent, NOW, limit=5)
    assert is_locked(recent + [NOW - timedelta(minutes=14)], NOW, limit=5)
    assert not is_locked(recent + [NOW - timedelta(minutes=15)], NOW, limit=5)
```

- [ ] **Step 3: Implement the rules** (`app/identity/rules.py`)

```python
"""Pure identity rules: usernames, passwords, scrypt hashing, tokens, lockout (FR-01–03, SRS §9)."""

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.shared.errors import ValidationError

USERNAME = re.compile(r"[a-z0-9_]{3,32}")
SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_BYTES, KEY_BYTES = 2**14, 8, 1, 16, 32
LOCKOUT_WINDOW = timedelta(minutes=15)
USERNAME_FAILURE_LIMIT = 5
ADDRESS_FAILURE_LIMIT = 20


def normalize_username(raw: str | None) -> str:
    username = (raw or "").strip().lower()
    if not USERNAME.fullmatch(username):
        raise ValidationError.single("username", "Use 3–32 characters: lowercase letters, digits, or _.")
    return username


def validate_display_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not 1 <= len(name) <= 50:
        raise ValidationError.single("display_name", "Enter a name of 1–50 characters.")
    return name


def validate_password(raw: str | None, *, field: str = "password") -> str:
    if raw is None or not 10 <= len(raw) <= 128:
        raise ValidationError.single(field, "Use a password of 10–128 characters.")
    return raw


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, n, r, p, salt, expected = encoded.split("$")
        key = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, base64.b64decode(expected))


DUMMY_HASH = hash_password("float-timing-equaliser", salt=b"\x00" * SALT_BYTES)


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_locked(failure_times: Sequence[datetime], now: datetime, limit: int) -> bool:
    """True when at least ``limit`` failures happened within the 15 minutes before ``now``."""
    return sum(1 for moment in failure_times if now - moment < LOCKOUT_WINDOW) >= limit
```

- [ ] **Step 4: Failing service tests** (`tests/identity/test_service.py`). Use the `conn` fixture and `FixedClock`. Each case is one test:
  - `register` stores a lowercase unique username. A second `register("ANA", …)` raises `ValidationError({"username": "That username is taken."})`.
  - `login` returns `(session, token)`. The stored `token_hash` equals `hash_token(token)`, and `expires_at` is `now + max_age`.
  - A wrong password and an unknown username both raise `AuthenticationError` with the identical message (AT-02).
  - After five failures within 15 minutes, the correct password raises `LockedOutError`. The same login succeeds once `clock.advance(minutes=15, seconds=1)` has moved past the window (AT-02).
  - A successful login resets the username count: four failures, a success, then four more failures is still not locked.
  - Twenty failures from one address across different usernames block every login from that address.
  - `resolve_session` returns the session while active and updates `last_seen_at` at most once a minute. It returns `None` and deletes the row after 48 hours idle, or after 14 days in total even if active (AT-01).
  - `logout` deletes the session. `change_password` rejects a wrong current password (`ValidationError` on `current_password`), deletes every other session of the user, keeps `keep_session_id`, and the new password works.
  - While locked, attempts are rejected without checking the password and are not recorded, so the lock cannot be extended forever. Attempts older than 24 hours are pruned on every login attempt.

- [ ] **Step 5: Implement the repository, service, and api.** `repository.py` holds the SQL: `insert_user`, `find_user_by_username`, `get_user`, `insert_session`, `find_session_by_token_hash` (a join with `users`), `touch_session`, `delete_session`, `delete_other_sessions`, `record_attempt`, `username_failures_since_last_success(key, since)`, `address_failures(address, since)`, and `prune_attempts(before)`. `service.login` works in this order:
  1. Normalize the username key; failures for an invalid username are still counted under the raw lowercase text.
  2. Prune old attempts.
  3. Reject if the username or the address is locked.
  4. Look up the user and verify the password. For an unknown user, verify against `DUMMY_HASH` so timing does not reveal existence.
  5. Record the attempt.
  6. On success, create a session with `new_token()` and `csrf_token = new_token()`.

  Services run inside the caller's `transaction(conn)`.
- [ ] **Step 6: Run** `pytest tests/identity -q` and `pytest -q`. Expected: all pass. **Commit:** `Add accounts with scrypt passwords, sessions, and login throttling`.

### Task 1.2: Web security layer and authentication pages (FR-04, §9, NFR-10)

**Files:**
- Create: `app/web/middleware.py` (request IDs, structured request log, security headers), `app/web/security.py` (cookies and CSRF), `app/web/deps.py` (per-request connection, current session, login requirement), `app/web/forms.py` (error collection helper), `app/web/errors.py` (exception handlers), `app/web/auth.py` (register, login, logout routes)
- Create: `app/web/templates/auth/login.html`, `app/web/templates/auth/register.html`, `app/web/templates/error.html`, `app/web/templates/_form_field.html` (macro)
- Modify: `app/main.py` (add middleware, handlers, auth router), `app/web/templates/base.html` (navigation for signed-in users, with a logout button as a POST form)
- Test: `tests/web/__init__.py`, `tests/web/test_auth_flow.py`, `tests/web/test_security.py`

**Interfaces:**
- Produces:
  - `get_conn(request) -> Iterator[sqlite3.Connection]` (FastAPI dependency; one connection per request, closed afterwards)
  - `current_session(request, conn) -> Session | None`
  - `require_user` dependency, which raises `LoginRequired` and becomes a `303` redirect to `/login?next=<path>`
  - `verify_csrf` async dependency for every unsafe route
  - `render(request, template, context, *, status_code=200)`, which adds `csrf_token`, `current_user`, and `request_id` to every template
  - `collect(errors: dict, func, *args, **kwargs)`, which returns `func(...)` or merges its `ValidationError.errors` into `errors` and returns `None`
  - Cookie names `float_session` (session) and `float_csrf` (anonymous CSRF)
  - Response header `X-Request-ID` on every response

Rules to implement exactly:

- **CSRF.** Signed-in forms carry `csrf_token` equal to `sessions.csrf_token`. Anonymous forms (login, register) use the double-submit pattern: a random `float_csrf` cookie (`HttpOnly`, `SameSite=Lax`) whose value is also in the hidden field. Tokens are compared with `hmac.compare_digest`. On every unsafe method, an `Origin` header (or `Referer` when `Origin` is absent) must match the request's scheme and host; otherwise respond 403. API requests send the token in `X-CSRF-Token`.
- **Session cookie.** `HttpOnly; SameSite=Lax; Path=/`, plus `Secure` only when `settings.cookie_secure`. `Max-Age` equals `SESSION_MAX_DAYS`.
- **Headers** on every response except `/api/docs` (Swagger UI loads scripts from a CDN): `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: same-origin`.
- **Request log.** One JSON line per request on logger `float.request` with `request_id`, `method`, `route` (the path template, never the raw path with IDs), `status`, `duration_ms`, and `user_id`. It never contains cookies, tokens, form bodies, or passwords.
- **Error mapping.** `NotFoundError` → 404 page, `PermissionDeniedError` → 403, `ConflictError` → 409 with the message and a back link, an unhandled `ValidationError` → 400. Any other exception → 500 page showing only the request ID.

- [ ] **Step 1: Failing tests.**
  - `test_auth_flow.py`: registration signs the user in (303 → `/`, then `/setup` from Task 1.4). A duplicate username re-renders with the message and the submitted values. Login with a wrong password shows "Incorrect username or password." (status 400). The lockout message appears after five failures. Logout (a POST with the CSRF token) clears the cookie, after which `/` shows the anonymous page. `next` redirects only to local paths starting with `/`.
  - `test_security.py`:
    - POST without a token → 403.
    - POST with `Origin: https://evil.example` → 403.
    - Every response has the three headers and `X-Request-ID`.
    - The session cookie is `HttpOnly` and `SameSite=Lax`, with no `Secure` by default and `Secure` when `cookie_secure=True`.
    - A 500 page shows the request ID but not the exception text.
    - A log line contains the route template and no cookie value (use `caplog`).
- [ ] **Step 2: Implement** the modules above. Register `add_middleware` for headers and request IDs in `create_app`, the exception handlers, and `app.include_router(auth_router)`. Signed-in navigation: Dashboard, Transactions, and a "Log out" button in a POST form. Later days add links as pages appear.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Protect browser requests with sessions, CSRF tokens, and security headers`.

### Task 1.3: Ledger domain and audit trail (FR-06–08, FR-33 base)

**Files:**
- Create: `app/db/migrations/0003_audit.sql`, `app/db/migrations/0004_ledger.sql`
- Create: `app/ledger/__init__.py`, `app/ledger/rules.py`, `app/ledger/repository.py`, `app/ledger/service.py`, `app/ledger/api.py`
- Create: `app/application/__init__.py`, `app/application/audit.py`
- Test: `tests/ledger/__init__.py`, `tests/ledger/test_rules.py`, `tests/ledger/test_service.py`, `tests/application/__init__.py`, `tests/application/test_audit.py`

**Interfaces:**
- Produces (`app/ledger/api.py`):
  - Dataclasses: `LedgerSettings(user_id, tracking_start: date, opening_balance_cents: int)`; `TransactionDraft(kind, amount_cents, occurred_on, category_id=None, income_source=None, one_off=False, note="")`; `Transaction(id, user_id, kind, amount_cents, occurred_on, category_id, income_source, origin, one_off, note, version)`; `ExpenseRow(id, amount_cents, occurred_on, category_id, origin, one_off)`
  - Settings: `save_settings(conn, *, user_id, tracking_start, opening_balance_cents, today) -> LedgerSettings` (a second call raises `ConflictError`); `get_settings(conn, user_id) -> LedgerSettings | None`
  - Manual transactions: `create_manual(conn, *, user_id, draft, today, now) -> Transaction`; `update_manual(conn, *, user_id, transaction_id, version, draft, today, now) -> Transaction`; `delete_manual(conn, *, user_id, transaction_id, version) -> Transaction`; `get_transaction(conn, *, user_id, transaction_id) -> Transaction`; `list_transactions(conn, *, user_id, limit=50, before: tuple[date, int] | None = None) -> list[Transaction]`
  - Balance: `get_balance(conn, *, user_id, as_of) -> int`
  - Linked transactions, for coordinators only: `create_linked(conn, *, user_id, kind, origin, amount_cents, occurred_on, category_id, income_source, note, now) -> int`; `update_linked(conn, *, user_id, transaction_id, origin, amount_cents, occurred_on, category_id, now) -> None`; `delete_linked(conn, *, user_id, transaction_id, origin) -> None`
  - Queries: `has_allowance_income(conn, *, user_id, start, end_inclusive) -> bool`; `get_expense_rows(conn, *, user_id, start, end_exclusive) -> list[ExpenseRow]`
- Produces (`app/application/audit.py`): `record(conn, *, actor_user_id, entity_type, entity_id, action, now, before=None, after=None, household_id=None, request_id=None) -> int`. It serializes with `json.dumps(sort_keys=True, default=str)`.

- [ ] **Step 1: Migrations**

```sql
-- file: app/db/migrations/0003_audit.sql
-- Append-only audit trail, written in the same transaction as each mutation (FR-33).
-- household_id has no foreign key: households arrive in a later migration, and audit rows outlive records.
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    actor_user_id INTEGER REFERENCES users (id),
    household_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    request_id TEXT,
    occurred_at TEXT NOT NULL
) STRICT;
CREATE INDEX audit_by_household ON audit_events (household_id, id);
CREATE INDEX audit_by_actor ON audit_events (actor_user_id, id);

CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
```

```sql
-- file: app/db/migrations/0004_ledger.sql
-- Ledger: per-user settings and actual money movements (FR-05–07).
CREATE TABLE ledger_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    tracking_start_date TEXT NOT NULL,
    opening_balance_cents INTEGER NOT NULL
        CHECK (opening_balance_cents BETWEEN -100000000 AND 100000000)
) STRICT;

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    occurred_on TEXT NOT NULL,
    category_id INTEGER REFERENCES categories (id),
    income_source TEXT CHECK (income_source IN ('allowance', 'settlement', 'other')),
    origin TEXT NOT NULL CHECK (origin IN ('manual', 'bill', 'shared', 'settlement', 'import')),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (kind = 'income' AND income_source IS NOT NULL AND category_id IS NULL AND one_off = 0)
        OR (kind = 'expense' AND income_source IS NULL AND (
            (origin = 'settlement' AND category_id IS NULL)
            OR (origin <> 'settlement' AND category_id IS NOT NULL)))
    ),
    CHECK (origin <> 'settlement' OR kind = 'expense' OR income_source = 'settlement')
) STRICT;
CREATE INDEX transactions_by_user_date ON transactions (user_id, occurred_on, id);
```

- [ ] **Step 2: Failing tests.**
  - `test_rules.py`: `validate_draft` rejects each of the following with its field key, and collects several errors in one `ValidationError`:
    - kind other than income/expense (`kind`);
    - a future date or a date before tracking start (`occurred_on`);
    - an expense without a valid category (`category_id`);
    - an expense with an income source (`income_source`);
    - income with a category (`category_id`) or a one-off flag (`one_off`);
    - a manual income source of `settlement` (`income_source`), since only the settlement workflow creates those;
    - a note over 500 characters (`note`).
  - `test_service.py`:
    - **AT-04:** opening €100 + allowance €750 − groceries €25.40 gives `get_balance == 82460`. Editing the expense to €30 gives 82000; deleting it gives 85000.
    - A stale `version` on update or delete raises `ConflictError`.
    - Another user's transaction raises `NotFoundError`.
    - A linked transaction (`create_linked(origin="bill")`) makes `update_manual` and `delete_manual` raise `ConflictError("This transaction is managed by its bill, shared expense, or settlement.")` (AT-05).
    - An expense that makes the balance negative is accepted.
    - `list_transactions` orders by date descending, then ID descending.
    - `has_allowance_income` is true only for income with source `allowance`.
    - `get_expense_rows` returns expenses in `[start, end)` with their origin and one-off flag.
  - `test_audit.py`: `record` writes JSON with sorted keys. `UPDATE` and `DELETE` on `audit_events` raise `sqlite3.IntegrityError` ("append-only"). An audit row written inside a `transaction()` that later fails is rolled back with it (AT-25).
- [ ] **Step 3: Implement.**
  - `rules.py` defines `KINDS`, `MANUAL_INCOME_SOURCES = ("allowance", "other")`, `ORIGINS`, `DIRECTLY_EDITABLE = {"manual", "import"}`, `TransactionDraft`, and `validate_draft(draft, *, tracking_start, today, category_ids)`.
  - `repository.py` holds the SQL. The balance query is:

```sql
SELECT ls.opening_balance_cents + COALESCE(SUM(
         CASE t.kind WHEN 'income' THEN t.amount_cents ELSE -t.amount_cents END), 0)
FROM ledger_settings AS ls
LEFT JOIN transactions AS t
  ON t.user_id = ls.user_id AND t.occurred_on BETWEEN ls.tracking_start_date AND :as_of
WHERE ls.user_id = :user_id
GROUP BY ls.user_id
```

  - Every update uses `WHERE id = :id AND user_id = :user_id AND version = :version`. If that changes zero rows, distinguish a missing or foreign row (`NotFoundError`) from a stale version (`ConflictError`) with one follow-up `SELECT`.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. **Commit:** `Record ledger transactions with exact validation and an audit trail`.

### Task 1.4: Setup, transaction pages, and the recorded-balance dashboard (FR-05, FR-28, FR-39)

**Files:**
- Create: `app/db/migrations/0005_planning_settings.sql`
- Create: `app/planning/__init__.py`, `app/planning/repository.py`, `app/planning/service.py`, `app/planning/api.py` (settings only for now)
- Create: `app/application/context.py`, `app/application/setup.py`, `app/application/transactions.py`, `app/application/dashboard.py`
- Create: `app/web/setup.py`, `app/web/transactions.py`, `app/web/dashboard.py`, templates `setup.html`, `dashboard.html`, `transactions/list.html`, `transactions/form.html`
- Modify: `app/web/routes.py` (the home page becomes the dashboard for signed-in users and a welcome page with login and register links otherwise), `app/web/auth.py` (registration redirects to `/setup`), `app/main.py` (routers)
- Test: `tests/factories.py`, `tests/planning/__init__.py`, `tests/planning/test_settings.py`, `tests/application/test_setup.py`, `tests/web/test_setup_and_transactions.py`, `tests/web/test_authorization.py`

**Interfaces:**
- Produces:
  - `Actor(user_id: int, request_id: str | None)`
  - `SetupInput(tracking_start: date, opening_balance_cents: int, allowance_day: int, planned_allowance_cents: int)`
  - `complete_setup(conn, actor, data, clock) -> None`, which writes Ledger and Planning settings in one transaction and records an audit event; `is_setup_complete(conn, user_id) -> bool`; `update_planned_allowance(conn, actor, cents, clock)`
  - `add_transaction(conn, actor, draft, clock) -> Transaction`, `edit_transaction(conn, actor, transaction_id, version, draft, clock) -> Transaction`, `remove_transaction(conn, actor, transaction_id, version, clock) -> None`
  - `DashboardView(recorded_balance_cents, planned_allowance_cents, cycle: Cycle, allowance_reminder: bool)`; `dashboard(conn, user_id, clock) -> DashboardView`
  - `app/planning/api.py`: `PlanningSettings(user_id, allowance_day, planned_allowance_cents)`, `save_settings`, `get_settings`, `update_planned_allowance`, `get_cycle(conn, *, user_id, today) -> Cycle`
  - `tests/factories.py`: `make_user(conn, clock, username="ana", display_name="Ana", password="correct horse battery") -> User`; `complete_setup(conn, clock, user, *, tracking_start, opening_cents=0, allowance_day=1, planned_cents=75000)`; `add_expense(conn, clock, user, cents, on, *, category_id=1, one_off=False, note="") -> Transaction`; `add_income(conn, clock, user, cents, on, *, source="allowance") -> Transaction`; `sign_up(client, username, password="correct horse battery") -> None`, which registers through the HTML form, including CSRF

- [ ] **Step 1: Migration**

```sql
-- file: app/db/migrations/0005_planning_settings.sql
-- Planning settings captured during setup (FR-05). Bills and goals arrive on day 2.
CREATE TABLE planning_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    allowance_day INTEGER NOT NULL CHECK (allowance_day BETWEEN 1 AND 31),
    planned_allowance_cents INTEGER NOT NULL DEFAULT 75000
        CHECK (planned_allowance_cents BETWEEN 1 AND 100000000)
) STRICT;
```

- [ ] **Step 2: Failing tests.**
  - `test_setup.py`:
    - Setup stores both settings atomically; a failure injected in the Planning write leaves no Ledger settings.
    - A start date after today is rejected.
    - Setup creates no income (FR-05).
    - A second setup raises `ConflictError`.
    - Only the planned allowance can change afterwards.
  - `test_setup_and_transactions.py`:
    - A signed-in user without setup is redirected from `/` and `/transactions` to `/setup`.
    - The setup form shows the fixed-after-setup warning.
    - Invalid fields re-render with messages and the submitted values kept.
    - Adding, editing, and deleting a transaction updates the dashboard balance. A duplicate submit of the add form after the redirect does not create two records, because POST-redirect-GET means reloading the page issues a GET.
    - The allowance reminder shows until an `allowance` income is recorded in the current cycle; unrelated income does not clear it (AT-21).
    - Notes containing `<script>` render escaped.
  - `test_authorization.py` (the start of the AT-03 matrix): user B requesting GET `/transactions/{a_id}/edit`, POST `/transactions/{a_id}/edit`, or POST `/transactions/{a_id}/delete` for user A's transaction gets 404. Anonymous requests get a 303 to `/login`. Each later day adds rows for its new routes.
- [ ] **Step 3: Implement.** Web handlers follow one pattern:
  1. Parse every field with `collect()`.
  2. If there are errors, re-render with status 400.
  3. Otherwise call the use case. On `ValidationError`, re-render with its errors; on success, redirect with `303`.

  The dashboard shows recorded balance, planned allowance (labelled "expected, not received"), next allowance date, days remaining, and the reminder. Safe-to-spend is added on day 2.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. Smoke test in a browser: register, set up, add an expense, and see the balance change. **Commit:** `Add setup, transaction pages, and the recorded-balance dashboard`.

### Task 1.5: Decisions, AI log, and delivery

**Files:** Create `ADR.md`. Modify `AI_USAGE.md`, `README.md` (features available so far), and `planned-commits.md`.

- [ ] **Step 1:** Create `ADR.md` with a header explaining the format. Each ADR has an ID, date, status, context, decision, alternatives considered, and consequences.
  - **ADR-1 Stack**, dated 2026-10-01: FastAPI + Jinja2 + stdlib `sqlite3` in one process. Alternatives were Django, Flask, and an SPA with a separate API; consequences include no ORM, SQL written by hand, and pinned versions.
  - **ADR-2 Domain boundaries**, dated 2026-10-01: three domains plus Identity and Insights, `api.py`-only imports enforced by a test, application coordinators, and a single-transaction coupling with a saga/outbox extraction seam.

  Both entries record the day they were actually decided.
- [ ] **Step 2:** Add today's AI log rows, mark the student-explanation column as pending, and tick `planned-commits.md`.
- [ ] **Step 3:** Run `pytest -q`, the coverage command for the modules that now exist, and `git diff --check`. **Commit** `Record the stack and domain-boundary decisions`, then push, create the PR `Build accounts and the personal ledger`, and merge it.

---

## Day 2 — Friday 2 October: Planning, safe-to-spend, and personal insight (P0 + P1)

**Deliverable:**
- *P0:* recurring personal bills with idempotent materialization; pay, undo, skip, edit, and split; savings goals; and a dashboard showing safe-to-spend per day with its breakdown, shortfall, allowance reminder, and purchase preview.
- *P1, in priority order:* the insight that needs only personal data, namely pace, runway, the cash projection, the next-cycle outlook, goal contribution plans, budgets, and unusual-expense flags.

Household terms are zero until day 3 wires them in. Covers FR-09–16 and FR-27–31. Tests: AT-06–12, AT-19 (personal part), AT-20 (bill payment), AT-22 (pure rules), and AT-23.

### Task 2.1: Bill series and materialization (FR-09–11)

**Files:**
- Create: `app/db/migrations/0006_planning.sql`
- Create: `app/planning/rules.py`
- Modify: `app/planning/repository.py`, `app/planning/service.py`, `app/planning/api.py`
- Test: `tests/planning/test_rules.py`, `tests/planning/test_bills.py`

**Interfaces:**
- Produces:
  - `BillSeries(id, user_id, name, amount_cents, category_id, rule: Rule, materialized_through: date | None, ended: bool, version)`
  - `Occurrence(id, series_id, name, category_id, scheduled_date, due_date, amount_cents, skipped: bool, paid_transaction_id: int | None, version)`
  - `occurrence_status(occurrence, *, today, next_allowance) -> str`, returning `paid`, `skipped`, `overdue`, `reserved`, or `upcoming`
  - `create_series(conn, *, user_id, name, amount_cents, category_id, rule, tracking_start, now) -> BillSeries`
  - `ensure_materialized(conn, *, user_id, horizon_end) -> int` (the number of rows inserted)
  - `list_occurrences(conn, *, user_id, start, end_exclusive) -> list[Occurrence]`
  - `get_occurrence(conn, *, user_id, occurrence_id) -> Occurrence`
  - `PlanningObligations(personal_bills_cents, protected_savings_cents, goal_plan_reserve_cents, occurrences: tuple[Occurrence, ...])`
  - `get_obligations(conn, *, user_id, cycle) -> PlanningObligations`

- [ ] **Step 1: Migration**

```sql
-- file: app/db/migrations/0006_planning.sql
-- Planning: recurring bills, savings goals, and budgets (FR-09–16).
CREATE TABLE bill_series (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INTEGER NOT NULL REFERENCES categories (id),
    freq TEXT NOT NULL CHECK (freq IN ('once', 'weekly', 'monthly')),
    interval INTEGER NOT NULL CHECK (interval BETWEEN 1 AND 52),
    anchor_date TEXT NOT NULL,
    until_date TEXT,
    max_count INTEGER CHECK (max_count BETWEEN 1 AND 500),
    materialized_through TEXT,
    ended_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    CHECK (until_date IS NULL OR max_count IS NULL),
    CHECK (freq <> 'monthly' OR interval <= 12),
    CHECK (freq <> 'once' OR interval = 1)
) STRICT;

CREATE TABLE bill_occurrences (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES bill_series (id) ON DELETE RESTRICT,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    scheduled_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    skipped_at TEXT,
    paid_transaction_id INTEGER UNIQUE REFERENCES transactions (id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (series_id, scheduled_date),
    CHECK (skipped_at IS NULL OR paid_transaction_id IS NULL)
) STRICT;
CREATE INDEX bill_occurrences_by_user_due ON bill_occurrences (user_id, due_date);

CREATE TABLE savings_goals (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    target_cents INTEGER NOT NULL CHECK (target_cents BETWEEN 1 AND 100000000),
    target_date TEXT,
    priority INTEGER NOT NULL DEFAULT 2 CHECK (priority IN (1, 2, 3)),
    auto_reserve INTEGER NOT NULL DEFAULT 0 CHECK (auto_reserve IN (0, 1)),
    archived_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE goal_movements (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES savings_goals (id) ON DELETE CASCADE,
    delta_cents INTEGER NOT NULL CHECK (delta_cents <> 0 AND delta_cents BETWEEN -100000000 AND 100000000),
    moved_on TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 200),
    created_at TEXT NOT NULL
) STRICT;
CREATE INDEX goal_movements_by_goal ON goal_movements (goal_id, moved_on);

CREATE TRIGGER goal_movements_no_update BEFORE UPDATE ON goal_movements
BEGIN
    SELECT RAISE(ABORT, 'goal_movements is append-only');
END;

CREATE TABLE budget_templates (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories (id),
    limit_cents INTEGER NOT NULL CHECK (limit_cents BETWEEN 0 AND 100000000),
    PRIMARY KEY (user_id, category_id)
) STRICT;

CREATE TABLE category_budgets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories (id),
    cycle_start TEXT NOT NULL,
    limit_cents INTEGER NOT NULL CHECK (limit_cents BETWEEN 0 AND 100000000),
    UNIQUE (user_id, category_id, cycle_start)
) STRICT;
```

- [ ] **Step 2: Failing tests.**
  - `test_rules.py`: `occurrence_status` for each state with `today = 2026-09-20` and `next_allowance = 2026-10-01`: due 25 Sep → `reserved`; due 15 Sep and unpaid → `overdue`; due exactly 1 Oct → `upcoming` (AT-08); paid → `paid`; skipped → `skipped`.
  - `test_bills.py`:
    - An anchor before tracking start raises `ValidationError` on `anchor_date` (FR-09).
    - Materializing twice inserts nothing the second time.
    - Two connections materializing the same horizon one after the other create no duplicates (AT-07).
    - `materialized_through` equals `horizon_end − 1 day`.
    - A monthly series anchored 2026-09-25 materialized to horizon 2026-11-01 gives 25 Sep and 25 Oct.
    - `get_obligations` reserves 25 Sep (€120) but not an occurrence due on 1 Oct.
- [ ] **Step 3: Implement.** `ensure_materialized` runs inside the caller's transaction:

```python
def ensure_materialized(conn, *, user_id: int, horizon_end: date) -> int:
    inserted = 0
    for series in repository.active_series(conn, user_id=user_id):
        start = (series.materialized_through + timedelta(days=1)) if series.materialized_through else series.rule.anchor
        if start >= horizon_end:
            continue
        for day in expand(series.rule, start, horizon_end):
            inserted += repository.insert_occurrence_if_absent(
                conn, series_id=series.id, user_id=user_id, scheduled_date=day, amount_cents=series.amount_cents,
            )  # INSERT … ON CONFLICT (series_id, scheduled_date) DO NOTHING; returns rowcount
        repository.advance_watermark(conn, series_id=series.id, through=horizon_end - timedelta(days=1))
    return inserted
```

  The dashboard and bills pages open a `transaction()` just to materialize before reading. This is idempotent bookkeeping, not a user-visible mutation, so it is allowed on GET.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. **Commit:** `Materialize recurring bill occurrences idempotently`.

### Task 2.2: Pay, undo, skip, edit, end, and split (FR-12–13)

**Files:**
- Modify: `app/shared/recurrence.py` (add `split_rule`), `app/planning/service.py`, `app/planning/api.py`
- Create: `app/application/bills.py`, `app/web/bills.py`, templates `bills/index.html`, `bills/series_form.html`, `bills/occurrence.html`
- Test: `tests/shared/test_recurrence.py` (split cases), `tests/application/test_bills.py`, `tests/web/test_bills_pages.py`, plus new rows in `tests/web/test_authorization.py`

**Interfaces:**
- Produces:
  - `split_rule(rule, split_date) -> tuple[Rule, int | None]`: the shortened old rule (`until = split_date − 1 day`) and the remaining count for count-limited rules
  - Planning services:
    - `edit_occurrence(conn, *, user_id, occurrence_id, version, amount_cents, due_date)`
    - `skip(...)` and `unskip(...)`
    - `end_series(conn, *, user_id, series_id, version, today, now)`
    - `split_series(conn, *, user_id, occurrence_id, version, name, amount_cents, category_id, freq, interval, anchor, until, count, now) -> BillSeries`
    - `link_payment(conn, *, user_id, occurrence_id, version, transaction_id)`
    - `unlink_payment(conn, *, user_id, occurrence_id, version) -> int`, returning the unlinked transaction ID
  - Application: `pay_occurrence(conn, actor, occurrence_id, version, paid_on, clock) -> int` (the transaction ID) and `undo_payment(conn, actor, occurrence_id, version, clock) -> None`

```python
def split_rule(rule: Rule, split_date: date) -> tuple[Rule, int | None]:
    """End ``rule`` the day before ``split_date``; also return how many occurrences a count-limited rule still owes."""
    if split_date <= rule.anchor:
        raise ValidationError.single("split_date", "Edit the whole series instead of splitting at its first date.")
    before = count_before(rule, split_date)
    shortened = Rule(rule.freq, rule.interval, rule.anchor, until=split_date - timedelta(days=1))
    return shortened, (rule.count - before if rule.count is not None else None)
```

- [ ] **Step 1: Failing tests.**
  - Split rules:
    - A monthly rule anchored 5 July, split at 5 October, gives `until = 4 Oct` and `None`.
    - With `count=6`, it gives `until = 4 Oct` and a remaining count of 3.
    - Splitting at or before the anchor raises.
  - `test_bills.py` (application):
    - Paying creates exactly one `bill` expense for the occurrence's current amount and category and links it. A second pay raises `ConflictError` and creates nothing (AT-08).
    - If `link_payment` is monkeypatched to raise after the ledger insert, the ledger still has no transaction (fault injection).
    - Undo removes the expense and the link together; a paid occurrence cannot be edited or skipped until undone.
    - Fixture E split: gym €40 monthly from 5 July; July and August paid; 5 September unpaid and overdue. Splitting at 5 October with €45 ends the old series on 4 October, keeps 5 September at €40, and creates a new series from 5 October at €45. Splitting at 5 August is rejected (AT-09).
    - Moving an occurrence's due date and re-materializing does not recreate the original date.
    - Ending a series keeps overdue occurrences and removes unpaid ones due today or later.
    - Bill payment conserves discretionary funds (AT-20, first identity): paying moves `personal_bills` and cash by the same amount.
  - Authorization rows: another user's occurrence and series return 404 for every bills route.
- [ ] **Step 2: Implement.**
  - `split_series` follows SRS §4.2 steps 1–5 in the caller's transaction. When the split point is the first occurrence, the service instead updates the series in place, after checking that none of its occurrences are paid, deletes its unpaid occurrences, and re-materializes.
  - Every step writes an audit event.
  - The bills page lists this cycle's and next cycle's occurrences with their status text (not colour alone) and action buttons (Pay, Undo, Skip/Unskip, Edit, "Change this and future"), plus a form for new series.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Pay, undo, skip, and split bill series atomically`.

### Task 2.3: Savings goals (FR-14)

**Files:**
- Modify: `app/planning/service.py`, `app/planning/api.py`
- Create: `app/application/goals.py`, `app/web/goals.py`, template `goals.html`
- Test: `tests/planning/test_goals.py`, `tests/web/test_goals_pages.py`, authorization rows

**Interfaces:**
- Produces:
  - `Goal(id, user_id, name, target_cents, target_date, priority, auto_reserve, protected_cents, version)`
  - `create_goal(conn, *, user_id, name, target_cents, target_date=None, priority=2, auto_reserve=False, now) -> Goal`
  - `update_goal(conn, *, user_id, goal_id, version, name, target_cents, target_date, priority, auto_reserve) -> Goal`, which rejects a target below the protected amount
  - `move(conn, *, user_id, goal_id, delta_cents, moved_on, note, now) -> Goal`, where positive protects and negative releases
  - `list_goals(conn, *, user_id) -> list[Goal]`
  - `movements(conn, *, user_id, goal_id) -> list[tuple[date, int]]`, used by the goal plan in Task 2.6

- [ ] **Step 1: Failing tests (AT-10).**
  - Protecting €50 lowers `protected_savings_cents` by €50 and leaves the ledger balance unchanged.
  - A movement that would push the protected amount below zero or above the target raises `ValidationError` on `amount`.
  - Movements are append-only (an `UPDATE` raises).
  - Archiving (release everything, then archive) returns protected savings to zero.
  - Another user's goal returns 404.
- [ ] **Step 2: Implement.** `protected_cents` is `SUM(delta_cents)` over the goal's movements. The service validates the new total against `[0, target]`.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Track savings goals with protect and release movements`.

### Task 2.4: Safe-to-spend, reminder, and purchase preview (FR-27–29)

**Files:**
- Create: `app/insights/__init__.py`, `app/insights/safe_to_spend.py`, `app/insights/api.py`
- Modify: `app/application/dashboard.py`, `app/web/dashboard.py`, `app/web/templates/dashboard.html`
- Test: `tests/insights/__init__.py`, `tests/insights/test_safe_to_spend.py`, `tests/web/test_dashboard.py`

**Interfaces:**
- Produces: `SafeToSpendInputs`, `SafeToSpend`, `Preview`, `compute(inputs, cycle) -> SafeToSpend`, `preview(result, cost_cents) -> Preview`. The day 2 `DashboardView` adds `safe: SafeToSpend` and `preview: Preview | None`.

```python
# file: app/insights/safe_to_spend.py
"""Safe-to-spend composition (SRS §4.5). Pure: callers supply integer cents and the cycle."""

from dataclasses import dataclass

from app.shared.dates import Cycle
from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS


@dataclass(frozen=True)
class SafeToSpendInputs:
    recorded_balance_cents: int
    personal_bills_cents: int = 0
    household_bill_shares_cents: int = 0
    protected_savings_cents: int = 0
    household_payables_cents: int = 0
    goal_plan_reserve_cents: int = 0

    @property
    def reserved_cents(self) -> int:
        return (
            self.personal_bills_cents
            + self.household_bill_shares_cents
            + self.protected_savings_cents
            + self.household_payables_cents
            + self.goal_plan_reserve_cents
        )


@dataclass(frozen=True)
class SafeToSpend:
    inputs: SafeToSpendInputs
    cycle: Cycle
    discretionary_cents: int

    @property
    def shortfall_cents(self) -> int:
        return max(0, -self.discretionary_cents)

    @property
    def daily_cents(self) -> int:
        return max(0, self.discretionary_cents) // self.cycle.days_remaining


@dataclass(frozen=True)
class Preview:
    cost_cents: int
    after_cents: int
    after_daily_cents: int
    after_shortfall_cents: int


def compute(inputs: SafeToSpendInputs, cycle: Cycle) -> SafeToSpend:
    return SafeToSpend(inputs, cycle, inputs.recorded_balance_cents - inputs.reserved_cents)


def preview(result: SafeToSpend, cost_cents: int) -> Preview:
    """What a purchase would leave. Works on a copy of the numbers and never writes anything."""
    if not 1 <= cost_cents <= MAX_CENTS:
        raise ValidationError.single("cost", "Enter a cost greater than zero.")
    after = result.discretionary_cents - cost_cents
    return Preview(cost_cents, after, max(0, after) // result.cycle.days_remaining, max(0, -after))
```

- [ ] **Step 1: Failing tests.**
  - `test_safe_to_spend.py`, using SRS Fixture A without the household (this is also the v0.1 fixture): balance €500, bills €120, protected €50, today 20 September → discretionary €330 and **€30.00/day**. Preview €110 → €220 and **€20.00/day**. Preview €350 → **€20.00 shortfall** and €0.00/day. €10 over 3 days → €3.33/day (rounded down). A negative discretionary amount shows zero per day plus the exact shortfall. Then the full Fixture A inputs: 50000, 12000, 1200, 5000, 1000 → 30800 and **2800/day**.
  - `test_dashboard.py`: the page shows every term of the breakdown with links (to bills, goals, and transactions). A shortfall banner uses text as well as colour. `GET /?cost=110` shows the preview and leaves the database unchanged; compare a `SELECT` of every table before and after (AT-19).
- [ ] **Step 2: Implement.**
  - The dashboard use case: open `transaction()`; `ensure_materialized(horizon_end)`; get the balance, obligations, and cycle; build `SafeToSpendInputs` with household terms 0 (day 3 fills them) and the goal reserve 0 (Task 2.6 fills it); then `compute`.
  - The preview comes from the query parameter `cost`, parsed with `parse_money(field="cost")`, because it is read-only and allowed on GET.
  - The template labels planned allowance as expected, not counted.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Compute safe-to-spend with breakdown, reminder, and purchase preview`.

### Task 2.5: Forecast, pace, and next-cycle outlook (FR-30, §4.7)

**Files:**
- Create: `app/insights/forecast.py`, `app/insights/consumption.py`, `app/web/templates/forecast.html`
- Modify: `app/insights/api.py`, `app/application/dashboard.py` (adds `forecast(conn, user_id, clock)`), `app/web/dashboard.py` (`GET /forecast`)
- Test: `tests/insights/test_forecast.py`, `tests/insights/test_consumption.py`, `tests/web/test_forecast_page.py`

**Interfaces:**
- Produces:
  - `consumption_by_category(expense_rows, share_rows) -> dict[int, int]`, which counts origins `manual`, `bill`, and `import` plus shares
  - `variable_consumption(expense_rows, share_rows) -> int`, which excludes bills, household-bill shares, and one-off items
  - `ForecastInputs(cycle, tracking_start, allowance_day, discretionary_cents, daily_cents, recorded_balance_cents, protected_savings_cents, household_payables_cents, planned_allowance_cents, commitments: tuple[tuple[date, int], ...], variable_consumption_cents, next_cycle_goal_plan_cents=0)`
  - `DayProjection(day, conservative_cents, expected_cents)`
  - `Forecast(pace_cents | None, effective_pace_cents, runway_days | None, run_out_date | None, status, carry_over_cents, lowest_expected: DayProjection, conservative_goes_negative: bool, dips_into_savings: bool, next_free_cents, next_daily_cents, next_shortfall_cents, timeline: tuple[DayProjection, ...])`
  - `pace_window_days(today, tracking_start) -> int`; `compute_forecast(inputs) -> Forecast`

Until Task 3.4, the application layer passes no share rows, no household commitments, and zero payables, so the page reflects personal data only. The pure `compute_forecast` tests already use the full Fixture A numbers.

```python
def compute_forecast(inputs: ForecastInputs) -> Forecast:
    cycle, today = inputs.cycle, inputs.cycle.today
    window = pace_window_days(today, inputs.tracking_start)
    pace = inputs.variable_consumption_cents // window if window >= 7 else None
    effective = pace if pace is not None else inputs.daily_cents
    if inputs.discretionary_cents < 0:
        runway = 0
    elif effective == 0:
        runway = None  # unlimited
    else:
        runway = inputs.discretionary_cents // effective
    run_out = today + timedelta(days=runway) if runway is not None else None
    status = "on_track" if runway is None or runway >= cycle.days_remaining else "at_risk"
    carry_over = max(0, inputs.discretionary_cents - effective * cycle.days_remaining)
    paydays = allowance_dates(today + timedelta(days=1), cycle.horizon_end, inputs.allowance_day)
    timeline, day = [], today
    while day < cycle.horizon_end:
        committed = sum(cents for due, cents in inputs.commitments if due <= day) + inputs.household_payables_cents
        conservative = inputs.recorded_balance_cents - committed - effective * ((day - today).days + 1)
        expected = conservative + inputs.planned_allowance_cents * sum(1 for payday in paydays if payday <= day)
        timeline.append(DayProjection(day, conservative, expected))
        day += timedelta(days=1)
    lowest = min(timeline, key=lambda point: (point.expected_cents, point.day))
    next_commitments = inputs.next_cycle_goal_plan_cents + sum(
        cents for due, cents in inputs.commitments if cycle.next_allowance <= due < cycle.horizon_end
    )
    next_free = carry_over + inputs.planned_allowance_cents - next_commitments
    next_days = (cycle.horizon_end - cycle.next_allowance).days
    return Forecast(
        pace, effective, runway, run_out, status, carry_over, lowest,
        any(point.conservative_cents < 0 for point in timeline),
        lowest.expected_cents < inputs.protected_savings_cents,
        next_free, max(0, next_free) // next_days, max(0, -next_free), tuple(timeline),
    )
```

- [ ] **Step 1: Failing tests (AT-22).**
  - Fixture A base state: window 19, pace 1200, runway 25, run-out 2026-10-15, `on_track`, carry-over 17600.
  - Lowest expected projection is 22600 on 2026-09-30; conservative on 2026-10-31 is −27800, so `conservative_goes_negative`; `next_daily_cents` is 2561 over 31 days.
  - Fixture C: daily 1000, runway 6, `at_risk`, carry-over 0.
  - With 6 complete days of history, pace is `None`, the page says "not enough history", and `effective_pace == daily`.
  - Consumption: Ana's €30 groceries she paid count €10 in groceries, and settlement transfers count nothing.
- [ ] **Step 2: Implement.** The forecast page shows the pace against safe-to-spend, the run-out date, and a small inline SVG with two lines (conservative and expected) marking the lowest point. Colour is never the only signal.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Forecast pace, runway, cash projection, and next-cycle outlook`.

### Task 2.6: Goal plan, budgets, and unusual expenses (FR-15, FR-16, FR-31, §4.6, §4.8)

**Files:**
- Modify: `app/planning/rules.py`, `service.py`, `api.py` (goal plan, budget templates and overrides); `app/application/dashboard.py` (goal reserve term and next-cycle goal plan)
- Create: `app/insights/anomaly.py`, `app/web/budgets.py`, template `budgets.html`
- Test: `tests/planning/test_goal_plan.py`, `tests/planning/test_budgets.py`, `tests/insights/test_anomaly.py`, `tests/web/test_budgets_page.py`

**Interfaces:**
- Produces:
  - `GoalPlan(cycles_left, planned_cents, pending_reserve_cents, status)`
  - `goal_plan(*, target_cents, target_date, movements, cycle, allowance_day) -> GoalPlan`
  - `next_cycle_contribution(plan, *, target_cents, protected_now_cents) -> int`
  - `effective_limit(conn, *, user_id, category_id, cycle_start) -> int | None`, `set_template(...)`, `set_override(...)`
  - `budget_state(consumption_cents, limit_cents) -> str | None`
  - `lower_median(values) -> int`, `unusual_threshold(history) -> int | None`, `is_unusual(amount_cents, history) -> bool`

```python
def goal_plan(*, target_cents, target_date, movements, cycle, allowance_day) -> GoalPlan:
    protected_now = sum(delta for moved_on, delta in movements if moved_on <= cycle.today)
    if protected_now >= target_cents:
        return GoalPlan(0, 0, 0, "complete")
    if target_date is None:
        return GoalPlan(0, 0, 0, "no_target_date")
    cycles_left = len(allowance_dates(cycle.start, target_date, allowance_day))
    if cycles_left == 0:
        return GoalPlan(0, 0, 0, "overdue")
    protected_at_start = sum(delta for moved_on, delta in movements if moved_on < cycle.start)
    planned = -(-max(0, target_cents - protected_at_start) // cycles_left)  # ceiling division
    this_cycle = sum(delta for moved_on, delta in movements if cycle.start <= moved_on <= cycle.today)
    pending = min(planned, max(0, planned - this_cycle), max(0, target_cents - protected_now))
    return GoalPlan(cycles_left, planned, pending, "on_plan" if pending == 0 else "behind")


def budget_state(consumption_cents: int, limit_cents: int | None) -> str | None:
    if limit_cents is None:
        return None
    if consumption_cents > limit_cents:
        return "over"
    if limit_cents > 0 and consumption_cents * 10 >= limit_cents * 8:
        return "warning"
    return "ok"
```

- [ ] **Step 1: Failing tests.**
  - Fixture B (AT-11): 6 cycles, planned 10000, pending 5000. Protecting 5000 more leaves discretionary unchanged; a further 3000 lowers it by 3000. October's plan is 9400. A target date on or before the cycle start is `overdue` with no reserve. Releasing re-reserves the undone part of this cycle's plan.
  - Budgets (AT-12): €60 against a €50 limit is `over` by €10; 80% gives `warning`; a template applies to a new cycle; an override beats the template; no limit differs from a zero limit, and a zero limit with any consumption is `over`.
  - Fixture F (AT-23): threshold 1300; 1400 is flagged and 1300 is not; 7 samples flag nothing.
- [ ] **Step 2: Implement.**
  - The dashboard's `goal_plan_reserve_cents` becomes the sum of `pending_reserve_cents` over auto-reserve goals.
  - The goals page shows status and plan.
  - The budgets page shows consumption, limit, and state per category, with text labels.
  - Unusual expenses get a flag and plain-language reason in the transactions list.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Plan goal contributions, budgets, and unusual-expense flags`.

### Task 2.7: Schema decision, AI log, and delivery

- [ ] **Step 1:** Add **ADR-3 Schema**, dated 2026-10-02: integer cents, STRICT tables, payment links instead of status flags, `scheduled_date` versus `due_date`, append-only movements and audit, cross-domain foreign keys as a documented monolith tradeoff. Update the SRS §7 ER diagram if the real schema differs.
- [ ] **Step 2:** Add AI log rows and tick `planned-commits.md`.
- [ ] **Step 3:** Run `pytest -q`, the coverage command, and `git diff --check`. **Commit** `Record the schema decision and log AI use`, then push, create the PR `Build recurring bills, goals, safe-to-spend, and the forecast`, and merge it.

---

## Day 3 — Saturday 3 October: Households, alerts, and the report draft (P0 + P1)

**Deliverable:**
- *P0:* flatmates create or join a household, record shared expenses with four split methods, see net balances and a settle-up plan, confirm settlements into both ledgers, and share recurring household bills. Safe-to-spend and the forecast now include household terms, and the full SRS Fixture A passes, including every conservation step.
- *Then:* the alert centre and activity feed, the JSON API if time remains, the last two ADRs, and a full first draft of the report.

Covers FR-17–26 and FR-32–35. Tests: AT-13–20, AT-22 (end to end), and AT-24–26.

### Task 3.1: Households, invitations, and membership (FR-17–19)

**Files:**
- Create: `app/db/migrations/0007_households.sql`
- Create: `app/households/__init__.py`, `rules.py`, `repository.py`, `service.py`, `api.py`
- Create: `app/application/authz.py`, `app/application/households.py`, `app/web/households.py`, templates `households/index.html`, `households/show.html` (tabs: balances, expenses, bills, settlements, members, activity), `households/join.html`
- Test: `tests/households/__init__.py`, `tests/households/test_codes.py`, `tests/households/test_membership.py`, `tests/web/test_households_pages.py`, authorization rows

**Interfaces:**
- Produces:
  - Rules: `new_invite_code() -> str` (10 Crockford base32 characters); `normalize_code(raw) -> str` (uppercase, drops spaces and hyphens, maps `O→0` and `I/L→1`); `hash_code(code) -> str`
  - `Household(id, name, owner_user_id, archived: bool, version)`; `Member(user_id, display_name, role, status)`
  - `create_household(conn, *, owner_id, name, now) -> Household`
  - `rename(...)`, `transfer_ownership(...)`, `archive(conn, *, household_id, version, now)`
  - `create_invitation(conn, *, household_id, created_by, now) -> str`, which returns the plain code once
  - `revoke_invitation(...)`, `join(conn, *, user_id, code, now) -> Household`
  - `leave_blockers(conn, *, household_id, user_id) -> list[str]`, `leave(...)`, `remove_member(...)`
  - `members(conn, *, household_id) -> list[Member]`
  - `app/application/authz.py`: `require_member(conn, user_id, household_id) -> Member`, which raises `NotFoundError` for non-members, and `require_owner(...)`, which raises `PermissionDeniedError` for non-owner members

- [ ] **Step 1: Migration**

```sql
-- file: app/db/migrations/0007_households.sql
-- Households: membership, invitations, shared expenses, household bills, settlements (FR-17–26).
CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    owner_user_id INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    archived_at TEXT,
    version INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE TABLE memberships (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    status TEXT NOT NULL CHECK (status IN ('active', 'left', 'removed')),
    joined_at TEXT NOT NULL,
    ended_at TEXT,
    CHECK ((status = 'active') = (ended_at IS NULL))
) STRICT;
CREATE UNIQUE INDEX one_active_membership ON memberships (household_id, user_id) WHERE status = 'active';
CREATE INDEX memberships_by_user ON memberships (user_id, status);

CREATE TABLE invitations (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households (id),
    code_hash TEXT NOT NULL UNIQUE CHECK (length(code_hash) = 64),
    created_by INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER REFERENCES users (id),
    used_at TEXT,
    revoked_at TEXT,
    CHECK ((used_by IS NULL) = (used_at IS NULL))
) STRICT;

CREATE TABLE shared_expenses (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households (id),
    payer_user_id INTEGER NOT NULL REFERENCES users (id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INTEGER NOT NULL REFERENCES categories (id),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND 100),
    spent_on TEXT NOT NULL,
    split_method TEXT NOT NULL CHECK (split_method IN ('equal', 'exact', 'percentage', 'shares')),
    one_off INTEGER NOT NULL DEFAULT 0 CHECK (one_off IN (0, 1)),
    payer_transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions (id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
CREATE INDEX shared_expenses_by_household ON shared_expenses (household_id, spent_on);

CREATE TABLE shared_expense_splits (
    expense_id INTEGER NOT NULL REFERENCES shared_expenses (id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users (id),
    weight INTEGER,
    share_cents INTEGER NOT NULL CHECK (share_cents >= 0),
    PRIMARY KEY (expense_id, user_id)
) STRICT;
CREATE INDEX shared_expense_splits_by_user ON shared_expense_splits (user_id);

CREATE TABLE household_bill_series (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households (id),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INTEGER NOT NULL REFERENCES categories (id),
    freq TEXT NOT NULL CHECK (freq IN ('once', 'weekly', 'monthly')),
    interval INTEGER NOT NULL CHECK (interval BETWEEN 1 AND 52),
    anchor_date TEXT NOT NULL,
    until_date TEXT,
    max_count INTEGER CHECK (max_count BETWEEN 1 AND 500),
    split_method TEXT NOT NULL CHECK (split_method IN ('equal', 'percentage', 'shares')),
    materialized_through TEXT,
    ended_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    CHECK (until_date IS NULL OR max_count IS NULL)
) STRICT;

CREATE TABLE household_bill_participants (
    series_id INTEGER NOT NULL REFERENCES household_bill_series (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    weight INTEGER NOT NULL CHECK (weight BETWEEN 1 AND 10000),
    PRIMARY KEY (series_id, user_id)
) STRICT;

CREATE TABLE household_bill_occurrences (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES household_bill_series (id) ON DELETE RESTRICT,
    scheduled_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    skipped_at TEXT,
    shared_expense_id INTEGER UNIQUE REFERENCES shared_expenses (id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (series_id, scheduled_date),
    CHECK (skipped_at IS NULL OR shared_expense_id IS NULL)
) STRICT;

CREATE TABLE settlements (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households (id),
    payer_user_id INTEGER NOT NULL REFERENCES users (id),
    payee_user_id INTEGER NOT NULL REFERENCES users (id),
    initiated_by INTEGER NOT NULL REFERENCES users (id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    paid_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected', 'cancelled')),
    reason TEXT NOT NULL DEFAULT '' CHECK (length(reason) <= 200),
    payer_transaction_id INTEGER UNIQUE REFERENCES transactions (id) ON DELETE RESTRICT,
    payee_transaction_id INTEGER UNIQUE REFERENCES transactions (id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    CHECK (payer_user_id <> payee_user_id),
    CHECK (initiated_by IN (payer_user_id, payee_user_id)),
    CHECK ((status = 'confirmed') = (payer_transaction_id IS NOT NULL AND payee_transaction_id IS NOT NULL)),
    CHECK ((status = 'pending') = (resolved_at IS NULL))
) STRICT;
CREATE INDEX settlements_by_household ON settlements (household_id, status);
```

- [ ] **Step 2: Failing tests (AT-13).**
  - `test_codes.py`: codes are 10 characters from the Crockford alphabet. `normalize_code(" ab-cd efgh jk ")` returns `"ABCDEFGHJK"`, and `O`/`I`/`L` map to `0`/`1`/`1`. Malformed input raises `ValidationError` with the generic invitation message.
  - `test_membership.py`:
    - Creating a household makes its creator the owner.
    - Joining needs completed setup and a valid, unexpired (under 72 hours), unused, unrevoked code. Expired, used, revoked, and unknown codes all give the same message.
    - A ninth active member is rejected. A user in three active households cannot join a fourth.
    - Leaving is blocked with listed reasons when the net is non-zero, a settlement is pending, or the user participates in an active household bill.
    - The owner must transfer ownership before leaving.
    - Archiving requires all nets to be zero and no pending settlements.
    - Non-members get `NotFoundError`, and a member attempting an owner action gets `PermissionDeniedError`.
- [ ] **Step 3: Implement.** Codes are generated with `secrets.choice(CROCKFORD)` and only the SHA-256 is stored. The household page shows the plain code once, right after creation. Every membership change writes an audit event with `household_id`.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. **Commit:** `Create households with single-use invitations and membership rules`.

### Task 3.2: Shared expenses and exact splits (FR-20–22)

**Files:**
- Modify: `app/households/rules.py`, `service.py`, `api.py`; `app/application/households.py`; `app/web/households.py`; templates `households/expense_form.html`
- Test: `tests/households/test_allocation.py` (examples and Hypothesis), `tests/application/test_shared_expenses.py`

**Interfaces:**
- Produces:
  - `SplitEntry(user_id: int, value: int | None)`
  - `allocate(amount_cents, method, entries) -> dict[int, int]`
  - `SharedExpense(id, household_id, payer_user_id, amount_cents, category_id, description, spent_on, split_method, one_off, shares: dict[int, int], version)`
  - Application coordinators, each running in one transaction:
    - `record_shared_expense(conn, actor, household_id, draft, clock) -> SharedExpense`, which writes the Households rows, the payer's `shared` Ledger expense for the full amount, and an audit event
    - `edit_shared_expense(conn, actor, expense_id, version, draft, clock)`
    - `delete_shared_expense(conn, actor, expense_id, version, clock)`

```python
def allocate(amount_cents: int, method: str, entries: Sequence[SplitEntry]) -> dict[int, int]:
    """Split ``amount_cents`` exactly (SRS §4.3): the shares always sum to the amount."""
    if method not in SPLIT_METHODS:
        raise ValidationError.single("split_method", "Choose equal, exact, percentage, or shares.")
    ordered = sorted(entries, key=lambda entry: entry.user_id)
    if not ordered or len({entry.user_id for entry in ordered}) != len(ordered):
        raise ValidationError.single("participants", "Choose each participant once.")
    if method == "exact":
        values = [entry.value for entry in ordered]
        if any(value is None or value < 0 for value in values):
            raise ValidationError.single("split", "Enter an amount of zero or more for each participant.")
        if sum(values) != amount_cents:
            raise ValidationError.single(
                "split", f"The amounts add up to {format_money(sum(values))}, not {format_money(amount_cents)}."
            )
        shares = [int(value) for value in values]
    else:
        if method == "equal":
            weights = [1] * len(ordered)
        else:
            weights = [entry.value for entry in ordered]
            low, high = (0, 10_000) if method == "percentage" else (1, 100)
            if any(weight is None or not low <= weight <= high for weight in weights):
                raise ValidationError.single("split", "Enter a valid percentage or share for each participant.")
            if method == "percentage" and sum(weights) != 10_000:
                raise ValidationError.single("split", "Percentages must add up to exactly 100%.")
        total = sum(weights)
        shares = [amount_cents * weight // total for weight in weights]
        ranking = sorted(range(len(ordered)), key=lambda i: (-(amount_cents * weights[i] % total), ordered[i].user_id))
        for index in ranking[: amount_cents - sum(shares)]:
            shares[index] += 1
    if not any(shares):
        raise ValidationError.single("split", "At least one participant must have a positive share.")
    return {entry.user_id: share for entry, share in zip(ordered, shares, strict=True)}
```

- [ ] **Step 1: Failing tests.**
  - Every Fixture D row: €100 split equally gives 3334/3333/3333; 33.33/33.33/33.34% of €10 gives 333/333/334; 2:1:1 shares of €10.01 give 501/250/250; exact €40/€35/€25 is accepted; exact summing to €99.99 is rejected; 50%/49.99% is rejected.
  - Hypothesis properties (AT-14): the shares sum exactly to the amount; each share is within 1 cent of `amount × weight / total`; the result is deterministic. A zero-weight percentage participant never receives a remainder cent.
  - Coordinators:
    - Recording creates the payer's linked `shared` ledger expense equal to the full amount.
    - Only the payer can edit or delete; others get `PermissionDeniedError`.
    - A stale version gives `ConflictError`, and the linked ledger expense changes in the same transaction (AT-15).
    - Participants must be active members.
    - The date must be within the payer's tracking period and not in the future.
    - Expenses generated by household bills cannot be edited here.
- [ ] **Step 2: Implement.** The expense form has participant checkboxes, a method selector, and a per-participant value field (the unit label changes with the method). A small inline script updates the running total, but the server stays the authority.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Split shared expenses exactly with largest-remainder allocation`.

### Task 3.3: Balances, settle-up plan, and settlements (FR-23–24)

**Files:**
- Modify: `app/households/rules.py`, `service.py`, `api.py`; `app/application/households.py`; `app/web/households.py`
- Test: `tests/households/test_balances.py`, `tests/application/test_settlements.py`

**Interfaces:**
- Produces:
  - Pure functions: `compute_nets(members, expenses, settlements) -> dict[int, int]`, `Transfer(from_user, to_user, amount_cents)`, and `simplify(nets) -> list[Transfer]`
  - `balances(conn, *, household_id) -> dict[int, int]`
  - `create_settlement(conn, *, household_id, initiated_by, payer_id, payee_id, amount_cents, paid_on, now)`
  - Application: `confirm_settlement(conn, actor, settlement_id, version, clock)`, `reject_settlement(..., reason)`, `cancel_settlement(...)`

```python
def compute_nets(members, expenses, settlements) -> dict[int, int]:
    """SRS §4.4. ``expenses``: (payer, amount, {user: share}); ``settlements``: confirmed (payer, payee, amount)."""
    nets = {member: 0 for member in members}
    for payer, amount, shares in expenses:
        nets[payer] = nets.get(payer, 0) + amount
        for user, share in shares.items():
            nets[user] = nets.get(user, 0) - share
    for payer, payee, amount in settlements:
        nets[payer] = nets.get(payer, 0) + amount
        nets[payee] = nets.get(payee, 0) - amount
    return nets


def simplify(nets: Mapping[int, int]) -> list[Transfer]:
    """Greedy settle-up: largest creditor against largest debtor, ties by user ID; at most n − 1 transfers."""
    remaining = {user: net for user, net in nets.items() if net}
    if sum(remaining.values()) != 0:
        raise ValueError("household nets must sum to zero")
    transfers: list[Transfer] = []
    while remaining:
        creditor = max(remaining, key=lambda user: (remaining[user], -user))
        debtor = min(remaining, key=lambda user: (remaining[user], user))
        amount = min(remaining[creditor], -remaining[debtor])
        transfers.append(Transfer(debtor, creditor, amount))
        for user, change in ((creditor, -amount), (debtor, amount)):
            remaining[user] += change
            if remaining[user] == 0:
                del remaining[user]
    return transfers
```

- [ ] **Step 1: Failing tests.**
  - Fixture A nets are Ana −1000, Ben +5000, Carla −4000, and the plan is Carla → Ben 4000, Ana → Ben 1000. Fixture G gives 4 → 1 3000, 3 → 1 2000, 2 → 1 1000.
  - Hypothesis (AT-16): for random expenses and settlements the nets sum to zero; the plan zeroes every net; the plan length is at most n − 1.
  - Settlements (AT-17):
    - Pending settlements do not change the nets.
    - Only the counterparty confirms or rejects; only the initiator cancels.
    - Confirming creates the payer's `settlement` expense (no category) and the payee's `settlement` income, both dated `paid_on`.
    - A second confirmation raises `ConflictError` and writes no ledger rows.
    - Terminal states are immutable.
    - In a race between two connections, confirm (first) and cancel (second, same version) produce exactly one winner and one pair of ledger rows.
    - An amount above the suggested transfer is accepted with a warning flag.
    - A `paid_on` before either user's tracking start is rejected.
- [ ] **Step 2: Implement.** State changes use `UPDATE settlements SET status = ?, … , version = version + 1 WHERE id = ? AND status = 'pending' AND version = ?`, and zero rows raises `ConflictError`, which rolls back the ledger writes. The balances tab lists each member's net with its itemised expenses and settlements, and the plan in plain language ("Carla pays Ben €40.00").
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Show household balances, settle-up plans, and confirmed settlements`.

### Task 3.4: Household bills and full safe-to-spend (FR-25–26, §4.5)

**Files:**
- Modify: `app/households/*` (bill series, participants, occurrences, `ensure_materialized`, `get_position`, `get_share_rows`), `app/application/households.py` (pay and undo for household occurrences), `app/application/dashboard.py` (household terms)
- Create: `tests/scenarios/__init__.py`, `tests/scenarios/flat_3b.py` (builds SRS Fixture A through the application layer)
- Test: `tests/application/test_household_bills.py`, `tests/application/test_conservation.py`, `tests/web/test_dashboard_fixture_a.py`

**Interfaces:**
- Produces:
  - `HouseholdPosition(bill_shares_cents, payables_cents, receivables_cents)`; `get_position(conn, *, user_id, window_end) -> HouseholdPosition`
  - `ShareRow(expense_id, spent_on, category_id, share_cents, one_off, from_household_bill)`; `get_share_rows(conn, *, user_id, start, end_exclusive) -> list[ShareRow]`
  - Application: `pay_household_occurrence(conn, actor, occurrence_id, version, paid_on, clock) -> SharedExpense`, `undo_household_payment(conn, actor, occurrence_id, version, clock)`
  - `build_flat_3b(conn, clock) -> Flat3B`, with the user IDs of Ana, Ben, and Carla and the IDs of the phone and internet occurrences

- [ ] **Step 1: Failing tests.**
  - `test_household_bills.py` (AT-18):
    - The owner creates "Internet" at €36, monthly from 28 September, split equally among the three. Each participant's position shows `bill_shares_cents == 1200` before payment.
    - An `exact` template is rejected, and so is an anchor before the creation date.
    - Editing an unpaid occurrence's amount changes everyone's share.
    - Paying creates a shared expense split from the template plus the payer's ledger expense, and turns the other members' shares into payables.
    - Undo (payer only, current version) restores everything.
  - `test_conservation.py` (AT-20):
    - Replay Fixture A steps 1–4 and assert Ana's discretionary is €308, €308, €308, then €260, and Carla's is unchanged in step 3.
    - A Hypothesis state machine applies random conversions (personal bill payment, household bill payment, settlement confirmation, protection up to the pending reserve) and asserts, for every user, `Δdiscretionary == −Δreceivables` (SRS §4.5).
  - `test_dashboard_fixture_a.py` (AT-19): Ana's dashboard on 20 September shows €500 balance, €120 bills, €12 household share, €50 protected, €10 owed to flatmates, discretionary **€308.00**, and **€28.00/day**. The previews show €18.00/day and a €42.00 shortfall.
- [ ] **Step 2: Implement.**
  - `get_position` sums, for every active household of the user:
    - `max(0, −net)` into payables and `max(0, net)` into receivables;
    - the user's `allocate(...)` share of every unpaid, unskipped household occurrence due before `window_end` in a series where they are a participant.
  - The dashboard passes `bill_shares_cents` and `payables_cents` into `SafeToSpendInputs` and links both terms to the household page.
- [ ] **Step 3: Wire households into insight.** The forecast and consumption now receive `get_share_rows`, the user's shares of unpaid household occurrences as commitments, and `household_payables_cents`. Add an end-to-end test (AT-22): Ana's forecast page in Fixture A shows pace €12.00/day, runway 25 days, lowest expected cash €226.00 on 30 September, and €25.61/day for October.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. **Commit:** `Reserve and pay household bills and complete the conservation tests`.

### Task 3.5: Alert centre and activity feed (FR-32, FR-33)

**Files:**
- Create: `app/db/migrations/0008_alerts.sql`, `app/insights/alerts.py` (pure `desired_alerts`), `app/insights/repository.py` (`sync_alerts`, `list_alerts`, `mark_read`, `dismiss`), `app/application/alerts.py`, `app/web/alerts.py`, templates `alerts.html` and the household activity tab
- Test: `tests/insights/test_alert_rules.py`, `tests/application/test_alerts.py`, `tests/web/test_activity_feed.py`

```sql
-- file: app/db/migrations/0008_alerts.sql
-- In-app alerts, deduplicated per user (FR-32), and each user's position in the audit feed.
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    subject_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    read_at TEXT,
    dismissed_at TEXT,
    resolved_at TEXT,
    UNIQUE (user_id, dedupe_key)
) STRICT;

CREATE TABLE alert_cursors (
    user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    last_audit_event_id INTEGER NOT NULL DEFAULT 0
) STRICT;
```

- [ ] **Step 1: Failing tests (AT-24, AT-25).**
  - Each SRS §4.9 rule fires on its condition with the exact dedupe key.
  - Evaluating twice creates no new rows.
  - Paying a bill resolves its `BILL_DUE_SOON` alert; a dismissed alert stays dismissed when its condition returns.
  - `HOUSEHOLD_EXPENSE_ADDED` reaches participants but never the actor, and the cursor advances.
  - The activity feed shows household events only to members, and personal events only to their owner.
- [ ] **Step 2: Implement.** `sync_alerts` works in three steps:
  1. Insert new keys.
  2. Update the message and clear `resolved_at` for keys that fire again.
  3. Set `resolved_at` on open keys that no longer fire, except `HOUSEHOLD_EXPENSE_ADDED`, which never auto-resolves.

  Evaluation runs when the dashboard or alerts page loads, and after each successful write, as a separate transaction after the write commits.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Add the alert centre and household activity feed`.

### Task 3.6: JSON API and idempotency keys (FR-34–35), only if time remains

**Files:**
- Create: `app/db/migrations/0009_idempotency.sql`, `app/api/__init__.py`, `app/api/v1/__init__.py`, `app/api/v1/problems.py`, `app/api/v1/idempotency.py`, `app/api/v1/routes.py`
- Test: `tests/api/__init__.py`, `tests/api/test_parity.py`, `tests/api/test_idempotency.py`

```sql
-- file: app/db/migrations/0009_idempotency.sql
-- Stored first responses for Idempotency-Key replays (FR-35), kept for 24 hours.
CREATE TABLE idempotency_keys (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    key TEXT NOT NULL CHECK (length(key) BETWEEN 1 AND 64),
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
) STRICT;
```

- [ ] **Step 1: Failing tests (AT-26).**
  - `GET /api/v1/dashboard` returns Fixture A's numbers as integer cents plus formatted strings.
  - Validation errors are `application/problem+json` with `errors` per field.
  - Replaying a POST with the same `Idempotency-Key` and body returns the stored response and creates nothing new; the same key with a different body returns 409.
  - Unsafe API requests without `X-CSRF-Token` return 403.
  - The authorization matrix rows mirror the HTML routes.
- [ ] **Step 2: Implement.** Each use case exists as an inner function `_name(conn, …)` that runs inside an open transaction, plus the public `name(conn, …)` that wraps it in `transaction()`. The idempotency layer calls the inner function inside the same transaction that stores the key, so the response and the effect commit together. Endpoints follow SRS §8.2.
- [ ] **Step 3: Run** `pytest -q`. Expected: all pass. **Commit:** `Expose the JSON API with idempotency keys`.

### Task 3.7: Final decisions, report draft, and delivery

- [ ] **Step 1:** Add **ADR-4 Testing strategy**, dated 2026-10-03: a pure-rule unit layer, Hypothesis properties for allocation, nets, recurrence, and conservation, integration tests on temporary SQLite files with fault injection, HTTP authorization matrices, mutation spot-checks, and a coverage target of 70% over business modules only. Explain why Hypothesis was chosen over hand-picked examples alone.
- [ ] **Step 2:** Add **ADR-5 Deliberate omission**, dated 2026-10-03, for example "no background scheduler: occurrences are materialized lazily and idempotently". The five ADRs now span three commit dates (1, 2, and 3 October).
- [ ] **Step 3:** Draft `docs/report.md` (4–5 pages) covering:
  - SMART goals and the planned SDLC compared with what actually happened, citing `planned-commits.md` and the git log;
  - architecture and schema diagrams that match the code;
  - the testing approach and current results;
  - risks and unfinished items;
  - the prescribed AI disclosure summary.

  Mark every measured number "to refresh on 4 October".
- [ ] **Step 4:** Add AI log rows and tick `planned-commits.md`.
- [ ] **Step 5:** Run `pytest -q`, the coverage command, and `git diff --check`. **Commit** `Record the testing decision, final ADR, and report draft`, then push, create the PR `Build households, alerts, and the report draft`, and merge it.

---

## Day 4 — Sunday 4 October: testing, fixes, polish, and final checks (deadline 23:59)

**Deliverable:** no new features. The whole product is checked against the PRD and SRS, every bug found is fixed test-first, the interface is polished after the student's own review, and the final measurements and documents are brought up to date. Merge by 20:00 to leave a buffer before 23:59. This is one of the six required commit days, so its fixes and improvements are real pushed commits.

The only feature work allowed today is finishing a P0 capability that slipped from 2 or 3 October, first thing, before the acceptance pass. P1 work that did not fit is cut and reported as not implemented, not squeezed in here.

### Task 4.1: Acceptance pass

**Files:** Create `scripts/perf_smoke.py` and `docs/acceptance-2026-10-04.md`.

- [ ] **Step 1: Fresh-clone check (AT-29).** Clone the repository into a temporary folder, create a virtualenv, `pip install -r requirements.txt`, start with `python app.py`, and register with no `.env`. Restart and confirm the data is kept. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`; both must report no problems.
- [ ] **Step 2: Full suite and coverage (NFR-08).** Run `pytest -q` and the SRS §11 coverage command, and record the real numbers.
- [ ] **Step 3: Performance (NFR-05, AT-31).** `scripts/perf_smoke.py` builds the synthetic dataset in a temporary database: a 3-member household, 5,000 transactions per member, 1,000 shared expenses, and 20 bill series. It times 50 dashboard use-case runs, prints p50 and p95, and times startup. Record the machine model, Python version, and numbers; never quote a number that was not measured.
- [ ] **Step 4: Walkthrough with the student.** In a browser, go through each PRD §6 journey:
  - onboarding;
  - daily use;
  - recurring bills;
  - living with flatmates, using two accounts in two browsers;
  - goals;
  - understanding spending;
  - alerts.

  Then do the AT-30 checks: a cross-site POST is rejected, notes are escaped, the security headers are present, keyboard-only use works, the layout holds at phone width, and the stale-edit conflict message appears. Write every problem in `docs/acceptance-2026-10-04.md` as a numbered issue with a severity: data or security, broken flow, or cosmetic.
- [ ] **Step 5: Commit** `Record the acceptance pass and performance measurements`.

### Task 4.2: Fix bugs test-first

- [ ] Handle each issue in severity order: data correctness and security first, then broken flows, then cosmetic.
  1. Write a test that reproduces it and watch it fail.
  2. Fix the code and run the whole suite.
  3. Commit `Fix <symptom>`, one commit per bug or small related group, and mark the issue fixed in `docs/acceptance-2026-10-04.md`.

### Task 4.3: UI enhancements

- [ ] Make the changes the student asks for after the walkthrough: layout, wording, navigation, empty states, charts, and narrow-screen behaviour. Keep NFR-07: every input has a label, everything works by keyboard, and warnings use text as well as colour.
- [ ] Each change keeps the suite green. Add or update a test where the change affects behaviour, for example a new link or form field. Commit `Improve <page or flow>` for each coherent change.

### Task 4.4: Final numbers, documents, and delivery

- [ ] **Step 1:** After all fixes, rerun the suite, the coverage command, and the performance script, and put the final numbers in the README and the report.
- [ ] **Step 2:** Finish the README (run, test, coverage and performance results, features, **not implemented** list, backup instructions). Update the report's numbers and its "what actually happened" section. Add AI log rows, and set the final status in `planned-commits.md`.
- [ ] **Step 3:** Check `git log --date=short --format=%ad main | sort | uniq -c`: there are six or more dates, and no date is above 40% of the total.
- [ ] **Step 4:** Run `pytest -q` and `git diff --check`. **Commit** `Record final measurements and verification results`, then push, create the PR `Verify, fix, and polish Float for submission`, and merge it by 20:00.

---

## P2 stretch tasks (only after every P0 and P1 task above is merged)

P2 is optional by design (PRD §7). If it is not reached, the README and report list FR-36–38 as not implemented.

### Task P2.1: CSV statement import (FR-36)

```sql
-- file: app/db/migrations/0010_imports.sql
-- Statement imports with duplicate detection and batch undo (FR-36).
CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    file_sha256 TEXT NOT NULL CHECK (length(file_sha256) = 64),
    filename TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('preview', 'committed', 'undone')),
    created_at TEXT NOT NULL,
    committed_at TEXT
) STRICT;

CREATE TABLE import_rows (
    batch_id INTEGER NOT NULL REFERENCES import_batches (id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    occurred_on TEXT,
    amount_cents INTEGER,
    description TEXT NOT NULL DEFAULT '',
    fingerprint TEXT,
    status TEXT NOT NULL CHECK (status IN ('new', 'duplicate', 'possible_duplicate', 'invalid', 'skipped', 'imported')),
    reason TEXT NOT NULL DEFAULT '',
    transaction_id INTEGER REFERENCES transactions (id),
    PRIMARY KEY (batch_id, row_number)
) STRICT;

ALTER TABLE transactions ADD COLUMN import_batch_id INTEGER REFERENCES import_batches (id);
ALTER TABLE transactions ADD COLUMN fingerprint TEXT;
CREATE INDEX transactions_by_fingerprint ON transactions (user_id, fingerprint);
```

- **Rules:**
  - The delimiter is whichever of `;` and `,` occurs more often in the header line.
  - The decimal separator is `,` when amounts match `-?\d+,\d{1,2}`.
  - Dates are accepted as `YYYY-MM-DD` or `DD/MM/YYYY`.
  - `fingerprint = sha256(f"{date}|{cents}|{normalized_description}")`, where the description is normalized by lowercasing and collapsing whitespace.
  - A row is a `duplicate` when its fingerprint exists for the user, and a `possible_duplicate` when an existing transaction has the same amount within ±2 days.
  - Limits are 1 MB and 2,000 rows.
- **Tests (AT-28):** a `;`-delimited Spanish statement with decimal commas parses correctly; each duplicate class is assigned correctly; commit is atomic, and an injected failure imports nothing; undo within 7 days removes the batch only if no row was edited; uploading the same file again warns.
- **Commit:** `Import bank statements with duplicate detection and batch undo`.

### Task P2.2: Category suggestions (FR-37)

- Add `category_rules(id, user_id, pattern, category_id, priority)` with `UNIQUE (user_id, pattern)`.
- `suggest_category(description, rules, history)` returns the first matching rule in priority order. Otherwise it takes the user's last 50 expenses sharing the description's first normalized word and returns their most frequent category when it has at least 3 matches, with ties going to the most recent. Otherwise it returns `None`.
- Suggestions only prefill forms and are never applied without confirmation. **Commit:** `Suggest categories from rules and history`.

### Task P2.3: Cycle review and savings sweep (FR-38)

- Pure `sweep_suggestion(unreserved_cents, goals) -> list[tuple[goal_id, cents]]`. It orders goals by priority, then earliest target date (none last), then ID. It fills each goal's next planned contribution first, then fills remaining targets in the same order, and never exceeds the unreserved amount.
- The review page for the previous cycle shows consumption against limits, the change in protected savings, and pace against safe-to-spend. "Accept sweep" creates goal movements in one transaction. **Commit:** `Add the cycle review with a suggested savings sweep`.

---

## Traceability

| Requirement | Task(s) | Acceptance tests |
|---|---|---|
| FR-01–03 Identity | 1.1, 1.2 | AT-01, AT-02 |
| FR-04 Authorization | 1.2, plus matrix rows in 1.4, 2.2, 2.3, 3.1–3.4, 3.6 | AT-03 |
| FR-05 Setup | 1.4 | AT-04, AT-29 |
| FR-06–07 Transactions and linked guard | 1.3, 1.4 | AT-04, AT-05 |
| FR-08 Categories | 0.3 (seed and triggers), 1.3 | AT-05 |
| FR-09–11 Bill series, materialization, status | 0.7, 2.1 | AT-07, AT-08 |
| FR-12–13 Pay/undo and edits | 2.2 | AT-08, AT-09 |
| FR-14 Goals | 2.3 | AT-10 |
| FR-15 Goal plan | 2.6 | AT-11 |
| FR-16 Budgets | 2.1 (tables), 2.6 | AT-12 |
| FR-17–19 Households and membership | 3.1 | AT-13 |
| FR-20–22 Shared expenses and splits | 3.2 | AT-14, AT-15 |
| FR-23–24 Balances and settlements | 3.3 | AT-16, AT-17 |
| FR-25–26 Household bills | 3.4 | AT-18 |
| FR-27, FR-29 Dashboard and preview | 2.4, 3.4 | AT-19, AT-20 |
| FR-28 Allowance reminder | 1.4 | AT-21 |
| FR-30 Forecast | 2.5, 3.4 (household terms) | AT-22 |
| FR-31 Consumption and anomalies | 2.5, 2.6 | AT-12, AT-23 |
| FR-32 Alerts | 3.5 | AT-24 |
| FR-33 Audit trail and feed | 1.3 (table and writes), 3.5 (feed) | AT-25 |
| FR-34–35 API and idempotency | 3.6 | AT-26 |
| FR-36–38 Stretch | P2.1–P2.3 | AT-28 |
| FR-39 Persistence | 0.3, 0.4, 1.4 | AT-29 |
| §4.1 cycles / §4.2 recurrence | 0.6 / 0.7, 2.2 | AT-06 / AT-07, AT-09 |
| §6.1 dependency rule | 0.4 | AT-27 |
| NFR-01–04, NFR-06 | 0.2–0.4 | AT-29 |
| NFR-05 performance | 4.1 | AT-31 |
| NFR-07 accessibility | every template; checked in 4.1 | AT-30 |
| NFR-08 coverage | measured daily; final in 4.4 | — |
| NFR-09 integrity | 4.1 | AT-29 |
| NFR-10 request IDs and logs | 1.2 | AT-30 |

## Self-review

- **Spec coverage.** Every FR, NFR, and acceptance test in the SRS maps to a task above. P2 is planned but optional.
- **Level of detail.** Day 0 is written out in full, because it is executed today. Days 1–3 give the complete SQL, the pure rules as code, exact interfaces, test cases with SRS fixture values, and algorithm code. Service and template code is specified by those interfaces and tests, not written in advance. That code is written on its own day, test-first, which is also what `planned-commits.md` requires. Day 4 adds no features: it is for acceptance testing, test-first bug fixes, UI polish, and final measurements.
- **Decisions this plan adds to the SRS:**
  - Materialization and alert evaluation may run inside GET requests, as idempotent bookkeeping.
  - The purchase preview uses `GET /?cost=` because it never writes.
  - `/api/docs` is exempt from the CSP so Swagger UI can load.
  - Attempts during a lockout are not recorded, so the lock cannot be extended forever.
  - Use cases have inner and outer forms so the API's idempotency keys commit together with the effect.
  - A goal without a target date shows the status "no target date".
  - `bill_series` also checks `interval = 1` for one-off bills.

  Record any of these that end up mattering in the ADRs.
- **Consistency check.** The names used across tasks match their producing task: `Session`, `User`, `TransactionDraft`, `Transaction`, `ExpenseRow`, `Occurrence`, `PlanningObligations`, `SafeToSpendInputs`, `HouseholdPosition`, `ShareRow`, `SplitEntry`, `Transfer`, `GoalPlan`, `ForecastInputs`, and `Forecast`. `HouseholdPosition.bill_shares_cents` feeds `SafeToSpendInputs.household_bill_shares_cents`, and `payables_cents` feeds `household_payables_cents`.
