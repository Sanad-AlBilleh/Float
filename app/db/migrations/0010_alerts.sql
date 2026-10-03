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
