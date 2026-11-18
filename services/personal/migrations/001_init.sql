-- personal service, migration 001: the Assignment 1 schema for Identity, Ledger, Planning and Insights,
-- ported from SQLite (A1 migrations 0001-0012) to SQL Server. One database, owned only by this service.
-- Port rules (plan.md section 7.1): INTEGER PRIMARY KEY -> INT IDENTITY; money -> BIGINT cents;
-- dates -> DATE; timestamps stay ISO-8601 UTC text written by the app; 0/1 flags -> BIT;
-- "UNIQUE on a nullable column" -> filtered unique index; SQLite triggers -> AFTER triggers with THROW.

CREATE TABLE users (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username NVARCHAR(32) NOT NULL UNIQUE,
    display_name NVARCHAR(50) NOT NULL,
    password_hash NVARCHAR(255) NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    password_changed_at NVARCHAR(40) NOT NULL,
    CONSTRAINT users_username_format CHECK (LEN(username) BETWEEN 3 AND 32
        AND username COLLATE Latin1_General_BIN NOT LIKE '%[^a-z0-9_]%'),
    CONSTRAINT users_display_name_length CHECK (LEN(display_name) BETWEEN 1 AND 50),
    CONSTRAINT users_password_hash_scheme CHECK (password_hash LIKE 'scrypt$%')
);

CREATE TABLE sessions (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash NVARCHAR(64) NOT NULL UNIQUE CHECK (LEN(token_hash) = 64),
    csrf_token NVARCHAR(100) NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    last_seen_at NVARCHAR(40) NOT NULL,
    expires_at NVARCHAR(40) NOT NULL
);
CREATE INDEX sessions_by_user ON sessions (user_id);

CREATE TABLE login_attempts (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username_key NVARCHAR(64) NOT NULL,
    client_address NVARCHAR(100) NOT NULL,
    attempted_at NVARCHAR(40) NOT NULL,
    succeeded BIT NOT NULL
);
CREATE INDEX login_attempts_by_username ON login_attempts (username_key, attempted_at);
CREATE INDEX login_attempts_by_address ON login_attempts (client_address, attempted_at);

-- Fixed categories (owner NULL) plus each user's own. Names are unique per owner; the database's
-- case-insensitive collation does what lower(name) did in SQLite.
CREATE TABLE categories (
    id INT IDENTITY(1,1) PRIMARY KEY,
    slug NVARCHAR(100) NOT NULL UNIQUE,
    name NVARCHAR(40) NOT NULL CHECK (LEN(name) BETWEEN 1 AND 40),
    owner_user_id INT NULL REFERENCES users (id) ON DELETE CASCADE,
    owner_key AS ISNULL(owner_user_id, 0) PERSISTED,
    CONSTRAINT categories_name_per_owner UNIQUE (owner_key, name)
);
CREATE INDEX categories_by_owner ON categories (owner_user_id);

SET IDENTITY_INSERT categories ON;
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
SET IDENTITY_INSERT categories OFF;
GO

CREATE TRIGGER categories_fixed ON categories AFTER UPDATE, DELETE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted WHERE owner_user_id IS NULL)
        THROW 50001, 'categories are fixed', 1;
END;
GO

-- Append-only audit trail (FR-33). household_id is a plain number: households live in the other service.
CREATE TABLE audit_events (
    id INT IDENTITY(1,1) PRIMARY KEY,
    actor_user_id INT NULL REFERENCES users (id),
    household_id INT NULL,
    entity_type NVARCHAR(50) NOT NULL,
    entity_id INT NULL,
    action NVARCHAR(50) NOT NULL,
    before_json NVARCHAR(MAX) NULL,
    after_json NVARCHAR(MAX) NULL,
    request_id NVARCHAR(64) NULL,
    occurred_at NVARCHAR(40) NOT NULL
);
CREATE INDEX audit_by_household ON audit_events (household_id, id);
CREATE INDEX audit_by_actor ON audit_events (actor_user_id, id);
GO

CREATE TRIGGER audit_events_append_only ON audit_events AFTER UPDATE, DELETE AS
BEGIN
    SET NOCOUNT ON;
    THROW 50002, 'audit_events is append-only', 1;
END;
GO

CREATE TABLE ledger_settings (
    user_id INT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    tracking_start_date DATE NOT NULL,
    opening_balance_cents BIGINT NOT NULL CHECK (opening_balance_cents BETWEEN -100000000 AND 100000000)
);

-- origin 'shared' and 'settlement' rows are created by the households service through
-- POST /internal/transactions; their IDs are stored there as plain numbers (ADR-7).
CREATE TABLE transactions (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    kind NVARCHAR(10) NOT NULL CHECK (kind IN ('income', 'expense')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    occurred_on DATE NOT NULL,
    category_id INT NULL REFERENCES categories (id),
    income_source NVARCHAR(20) NULL CHECK (income_source IN ('allowance', 'settlement', 'other')),
    origin NVARCHAR(20) NOT NULL CHECK (origin IN ('manual', 'bill', 'shared', 'settlement', 'import')),
    one_off BIT NOT NULL DEFAULT 0,
    note NVARCHAR(500) NOT NULL DEFAULT '',
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL,
    updated_at NVARCHAR(40) NOT NULL,
    CONSTRAINT transactions_kind_shape CHECK (
        (kind = 'income' AND income_source IS NOT NULL AND category_id IS NULL AND one_off = 0)
        OR (kind = 'expense' AND income_source IS NULL AND (
            (origin = 'settlement' AND category_id IS NULL)
            OR (origin <> 'settlement' AND category_id IS NOT NULL)))
    ),
    CONSTRAINT transactions_settlement_kind CHECK (origin <> 'settlement' OR kind = 'expense' OR income_source = 'settlement'),
    -- A1 needed two triggers for this (SQLite cannot add a CHECK later); a new table can just have it.
    CONSTRAINT transactions_settlement_income CHECK (income_source IS NULL OR income_source <> 'settlement' OR origin = 'settlement')
);
CREATE INDEX transactions_by_user_date ON transactions (user_id, occurred_on, id);

CREATE TABLE planning_settings (
    user_id INT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    allowance_day INT NOT NULL CHECK (allowance_day BETWEEN 1 AND 31),
    planned_allowance_cents BIGINT NOT NULL DEFAULT 75000 CHECK (planned_allowance_cents BETWEEN 1 AND 100000000),
    opening_includes_allowance BIT NOT NULL DEFAULT 0
);

CREATE TABLE bill_series (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name NVARCHAR(100) NOT NULL CHECK (LEN(name) BETWEEN 1 AND 100),
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INT NOT NULL REFERENCES categories (id),
    freq NVARCHAR(10) NOT NULL CHECK (freq IN ('once', 'weekly', 'monthly')),
    [interval] INT NOT NULL CHECK ([interval] BETWEEN 1 AND 52),
    anchor_date DATE NOT NULL,
    until_date DATE NULL,
    max_count INT NULL CHECK (max_count BETWEEN 1 AND 500),
    materialized_through DATE NULL,
    ended_at NVARCHAR(40) NULL,
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL,
    CHECK (until_date IS NULL OR max_count IS NULL),
    CHECK (freq <> 'monthly' OR [interval] <= 12),
    CHECK (freq <> 'once' OR [interval] = 1)
);

CREATE TABLE bill_occurrences (
    id INT IDENTITY(1,1) PRIMARY KEY,
    series_id INT NOT NULL REFERENCES bill_series (id),
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    scheduled_date DATE NOT NULL,
    due_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    skipped_at NVARCHAR(40) NULL,
    paid_transaction_id INT NULL REFERENCES transactions (id),
    version INT NOT NULL DEFAULT 1,
    CONSTRAINT bill_occurrences_once_per_date UNIQUE (series_id, scheduled_date),
    CHECK (skipped_at IS NULL OR paid_transaction_id IS NULL)
);
CREATE INDEX bill_occurrences_by_user_due ON bill_occurrences (user_id, due_date);
-- One expense pays at most one bill. SQL Server's UNIQUE would allow only one NULL, so it is filtered.
CREATE UNIQUE INDEX bill_occurrences_paid_once ON bill_occurrences (paid_transaction_id)
    WHERE paid_transaction_id IS NOT NULL;

CREATE TABLE savings_goals (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name NVARCHAR(100) NOT NULL CHECK (LEN(name) BETWEEN 1 AND 100),
    target_cents BIGINT NOT NULL CHECK (target_cents BETWEEN 1 AND 100000000),
    target_date DATE NULL,
    priority INT NOT NULL DEFAULT 2 CHECK (priority IN (1, 2, 3)),
    auto_reserve BIT NOT NULL DEFAULT 0,
    archived_at NVARCHAR(40) NULL,
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL
);

CREATE TABLE goal_movements (
    id INT IDENTITY(1,1) PRIMARY KEY,
    goal_id INT NOT NULL REFERENCES savings_goals (id) ON DELETE CASCADE,
    delta_cents BIGINT NOT NULL CHECK (delta_cents <> 0 AND delta_cents BETWEEN -100000000 AND 100000000),
    moved_on DATE NOT NULL,
    note NVARCHAR(200) NOT NULL DEFAULT '',
    created_at NVARCHAR(40) NOT NULL
);
CREATE INDEX goal_movements_by_goal ON goal_movements (goal_id, moved_on);
GO

CREATE TRIGGER goal_movements_no_update ON goal_movements AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    THROW 50003, 'goal_movements is append-only', 1;
END;
GO

CREATE TABLE budget_templates (
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    category_id INT NOT NULL REFERENCES categories (id),
    limit_cents BIGINT NOT NULL CHECK (limit_cents BETWEEN 0 AND 100000000),
    PRIMARY KEY (user_id, category_id)
);

CREATE TABLE category_budgets (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    category_id INT NOT NULL REFERENCES categories (id),
    cycle_start DATE NOT NULL,
    limit_cents BIGINT NOT NULL CHECK (limit_cents BETWEEN 0 AND 100000000),
    UNIQUE (user_id, category_id, cycle_start)
);

CREATE TABLE alerts (
    id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    type NVARCHAR(50) NOT NULL,
    dedupe_key NVARCHAR(200) NOT NULL,
    severity NVARCHAR(10) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message NVARCHAR(1000) NOT NULL,
    subject_url NVARCHAR(400) NOT NULL DEFAULT '',
    created_at NVARCHAR(40) NOT NULL,
    read_at NVARCHAR(40) NULL,
    dismissed_at NVARCHAR(40) NULL,
    resolved_at NVARCHAR(40) NULL,
    UNIQUE (user_id, dedupe_key)
);

-- last_audit_event_id is the position in the households service's activity feed (ADR-6).
CREATE TABLE alert_cursors (
    user_id INT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    last_audit_event_id INT NOT NULL DEFAULT 0
);

CREATE TABLE idempotency_keys (
    user_id INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    [key] NVARCHAR(64) NOT NULL CHECK (LEN([key]) BETWEEN 1 AND 64),
    request_hash NVARCHAR(64) NOT NULL CHECK (LEN(request_hash) = 64),
    status_code INT NOT NULL,
    response_json NVARCHAR(MAX) NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    PRIMARY KEY (user_id, [key])
);

-- GET /health writes and reads this one row to prove the service can use its own database.
CREATE TABLE health_probe (
    id INT PRIMARY KEY CHECK (id = 1),
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_probe (id, checked_at) VALUES (1, SYSUTCDATETIME());
