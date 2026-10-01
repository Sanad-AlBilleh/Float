-- Setup now asks whether the opening balance already holds the current cycle's allowance (FR-05, FR-28).
-- When it does, the dashboard does not ask the student to record that allowance again.
ALTER TABLE planning_settings
    ADD COLUMN opening_includes_allowance INTEGER NOT NULL DEFAULT 0 CHECK (opening_includes_allowance IN (0, 1));
