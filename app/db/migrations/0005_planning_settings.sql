-- Planning settings captured during setup (FR-05). Bills and goals arrive on day 2.
CREATE TABLE planning_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    allowance_day INTEGER NOT NULL CHECK (allowance_day BETWEEN 1 AND 31),
    planned_allowance_cents INTEGER NOT NULL DEFAULT 75000
        CHECK (planned_allowance_cents BETWEEN 1 AND 100000000)
) STRICT;
