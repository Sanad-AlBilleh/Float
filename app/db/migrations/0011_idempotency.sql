-- Stored first responses for Idempotency-Key replays (FR-35), kept for 24 hours.
CREATE TABLE idempotency_keys (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    key TEXT NOT NULL CHECK (length(key) BETWEEN 1 AND 64),
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
) STRICT;
