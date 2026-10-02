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
