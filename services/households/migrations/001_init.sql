-- households service, migration 001: the Assignment 1 Households schema (A1 migrations 0003, 0009, 0011),
-- ported from SQLite to SQL Server. One database, owned only by this service.
-- Users and ledger transactions live in the personal service's database, so every column that pointed
-- at users(id) or transactions(id) is now a plain INT with no foreign key (ADR-7). Foreign keys between
-- these households tables stay.

CREATE TABLE households (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(60) NOT NULL CHECK (LEN(name) BETWEEN 1 AND 60),
    owner_user_id INT NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    archived_at NVARCHAR(40) NULL,
    version INT NOT NULL DEFAULT 1
);

CREATE TABLE memberships (
    id INT IDENTITY(1,1) PRIMARY KEY,
    household_id INT NOT NULL REFERENCES households (id),
    user_id INT NOT NULL,
    role NVARCHAR(10) NOT NULL CHECK (role IN ('owner', 'member')),
    status NVARCHAR(10) NOT NULL CHECK (status IN ('active', 'left', 'removed')),
    joined_at NVARCHAR(40) NOT NULL,
    ended_at NVARCHAR(40) NULL,
    CONSTRAINT memberships_end_matches_status CHECK (
        (status = 'active' AND ended_at IS NULL) OR (status <> 'active' AND ended_at IS NOT NULL))
);
CREATE UNIQUE INDEX one_active_membership ON memberships (household_id, user_id) WHERE status = 'active';
CREATE INDEX memberships_by_user ON memberships (user_id, status);

CREATE TABLE invitations (
    id INT IDENTITY(1,1) PRIMARY KEY,
    household_id INT NOT NULL REFERENCES households (id),
    code_hash NVARCHAR(64) NOT NULL UNIQUE CHECK (LEN(code_hash) = 64),
    created_by INT NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    expires_at NVARCHAR(40) NOT NULL,
    used_by INT NULL,
    used_at NVARCHAR(40) NULL,
    revoked_at NVARCHAR(40) NULL,
    CONSTRAINT invitations_used_together CHECK (
        (used_by IS NULL AND used_at IS NULL) OR (used_by IS NOT NULL AND used_at IS NOT NULL))
);

-- payer_transaction_id is the payer's ledger expense in the personal service.
CREATE TABLE shared_expenses (
    id INT IDENTITY(1,1) PRIMARY KEY,
    household_id INT NOT NULL REFERENCES households (id),
    payer_user_id INT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INT NOT NULL,
    description NVARCHAR(100) NOT NULL CHECK (LEN(description) BETWEEN 1 AND 100),
    spent_on DATE NOT NULL,
    split_method NVARCHAR(12) NOT NULL CHECK (split_method IN ('equal', 'exact', 'percentage', 'shares')),
    one_off BIT NOT NULL DEFAULT 0,
    payer_transaction_id INT NOT NULL UNIQUE,
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL,
    updated_at NVARCHAR(40) NOT NULL
);
CREATE INDEX shared_expenses_by_household ON shared_expenses (household_id, spent_on);

CREATE TABLE shared_expense_splits (
    expense_id INT NOT NULL REFERENCES shared_expenses (id) ON DELETE CASCADE,
    user_id INT NOT NULL,
    weight INT NULL,
    share_cents BIGINT NOT NULL CHECK (share_cents >= 0),
    PRIMARY KEY (expense_id, user_id)
);
CREATE INDEX shared_expense_splits_by_user ON shared_expense_splits (user_id);

CREATE TABLE household_bill_series (
    id INT IDENTITY(1,1) PRIMARY KEY,
    household_id INT NOT NULL REFERENCES households (id),
    name NVARCHAR(100) NOT NULL CHECK (LEN(name) BETWEEN 1 AND 100),
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    category_id INT NOT NULL,
    freq NVARCHAR(10) NOT NULL CHECK (freq IN ('once', 'weekly', 'monthly')),
    [interval] INT NOT NULL CHECK ([interval] BETWEEN 1 AND 52),
    anchor_date DATE NOT NULL,
    until_date DATE NULL,
    max_count INT NULL CHECK (max_count BETWEEN 1 AND 500),
    split_method NVARCHAR(12) NOT NULL CHECK (split_method IN ('equal', 'percentage', 'shares')),
    materialized_through DATE NULL,
    ended_at NVARCHAR(40) NULL,
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL,
    CHECK (until_date IS NULL OR max_count IS NULL)
);

CREATE TABLE household_bill_participants (
    series_id INT NOT NULL REFERENCES household_bill_series (id),
    user_id INT NOT NULL,
    weight INT NOT NULL CHECK (weight BETWEEN 1 AND 10000),
    PRIMARY KEY (series_id, user_id)
);

CREATE TABLE household_bill_occurrences (
    id INT IDENTITY(1,1) PRIMARY KEY,
    series_id INT NOT NULL REFERENCES household_bill_series (id),
    scheduled_date DATE NOT NULL,
    due_date DATE NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    skipped_at NVARCHAR(40) NULL,
    shared_expense_id INT NULL REFERENCES shared_expenses (id),
    version INT NOT NULL DEFAULT 1,
    CONSTRAINT household_bill_occurrences_once_per_date UNIQUE (series_id, scheduled_date),
    CHECK (skipped_at IS NULL OR shared_expense_id IS NULL)
);
CREATE UNIQUE INDEX household_bill_paid_once ON household_bill_occurrences (shared_expense_id)
    WHERE shared_expense_id IS NOT NULL;

-- payer_transaction_id / payee_transaction_id are the two ledger rows in the personal service.
CREATE TABLE settlements (
    id INT IDENTITY(1,1) PRIMARY KEY,
    household_id INT NOT NULL REFERENCES households (id),
    payer_user_id INT NOT NULL,
    payee_user_id INT NOT NULL,
    initiated_by INT NOT NULL,
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    paid_on DATE NOT NULL,
    status NVARCHAR(10) NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected', 'cancelled')),
    reason NVARCHAR(200) NOT NULL DEFAULT '',
    payer_transaction_id INT NULL,
    payee_transaction_id INT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at NVARCHAR(40) NOT NULL,
    resolved_at NVARCHAR(40) NULL,
    CHECK (payer_user_id <> payee_user_id),
    CHECK (initiated_by IN (payer_user_id, payee_user_id)),
    CONSTRAINT settlements_confirmed_has_transactions CHECK (
        (status = 'confirmed' AND payer_transaction_id IS NOT NULL AND payee_transaction_id IS NOT NULL)
        OR (status <> 'confirmed' AND (payer_transaction_id IS NULL OR payee_transaction_id IS NULL))),
    CONSTRAINT settlements_pending_unresolved CHECK (
        (status = 'pending' AND resolved_at IS NULL) OR (status <> 'pending' AND resolved_at IS NOT NULL))
);
CREATE INDEX settlements_by_household ON settlements (household_id, status);
CREATE UNIQUE INDEX settlements_payer_transaction ON settlements (payer_transaction_id)
    WHERE payer_transaction_id IS NOT NULL;
CREATE UNIQUE INDEX settlements_payee_transaction ON settlements (payee_transaction_id)
    WHERE payee_transaction_id IS NOT NULL;

-- This service's own audit trail; the personal service reads household events from it over HTTP.
CREATE TABLE audit_events (
    id INT IDENTITY(1,1) PRIMARY KEY,
    actor_user_id INT NULL,
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

CREATE TABLE idempotency_keys (
    user_id INT NOT NULL,
    [key] NVARCHAR(64) NOT NULL CHECK (LEN([key]) BETWEEN 1 AND 64),
    request_hash NVARCHAR(64) NOT NULL CHECK (LEN(request_hash) = 64),
    status_code INT NOT NULL,
    response_json NVARCHAR(MAX) NOT NULL,
    created_at NVARCHAR(40) NOT NULL,
    PRIMARY KEY (user_id, [key])
);

CREATE TABLE health_probe (
    id INT PRIMARY KEY CHECK (id = 1),
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_probe (id, checked_at) VALUES (1, SYSUTCDATETIME());
