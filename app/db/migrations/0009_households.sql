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
