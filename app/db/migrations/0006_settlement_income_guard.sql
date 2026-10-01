-- Income marked as a settlement may only come from the settlement workflow (review fix, 1 October).
-- SQLite cannot add a CHECK constraint to an existing table, so triggers enforce it.
CREATE TRIGGER settlement_income_from_settlements_on_insert BEFORE INSERT ON transactions
WHEN NEW.income_source = 'settlement' AND NEW.origin <> 'settlement'
BEGIN
    SELECT RAISE(ABORT, 'settlement income must come from a settlement');
END;

CREATE TRIGGER settlement_income_from_settlements_on_update BEFORE UPDATE OF income_source, origin ON transactions
WHEN NEW.income_source = 'settlement' AND NEW.origin <> 'settlement'
BEGIN
    SELECT RAISE(ABORT, 'settlement income must come from a settlement');
END;
