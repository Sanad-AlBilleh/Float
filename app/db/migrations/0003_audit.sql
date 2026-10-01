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
