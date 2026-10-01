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
