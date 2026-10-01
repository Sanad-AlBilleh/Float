-- Identity: accounts, server-side sessions, and login throttling (FR-01–03).
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE
        CHECK (length(username) BETWEEN 3 AND 32 AND username NOT GLOB '*[^a-z0-9_]*'),
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 50),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
    created_at TEXT NOT NULL,
    password_changed_at TEXT NOT NULL
) STRICT;

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
) STRICT;
CREATE INDEX sessions_by_user ON sessions (user_id);

CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY,
    username_key TEXT NOT NULL,
    client_address TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1))
) STRICT;
CREATE INDEX login_attempts_by_username ON login_attempts (username_key, attempted_at);
CREATE INDEX login_attempts_by_address ON login_attempts (client_address, attempted_at);
