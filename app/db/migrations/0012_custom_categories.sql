-- Users may add their own expense categories (student request, 4 October). The fixed eleven stay fixed.
-- SQLite cannot drop a UNIQUE constraint, so the table is rebuilt: names are now unique per owner, not
-- globally. Foreign keys into categories are checked at commit, after the rebuilt table has every row.
PRAGMA defer_foreign_keys = ON;

CREATE TABLE categories_new (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
    owner_user_id INTEGER REFERENCES users (id) ON DELETE CASCADE
) STRICT;

INSERT INTO categories_new (id, slug, name) SELECT id, slug, name FROM categories;
DROP TABLE categories;
ALTER TABLE categories_new RENAME TO categories;

CREATE UNIQUE INDEX categories_name_per_owner ON categories (COALESCE(owner_user_id, 0), lower(name));
CREATE INDEX categories_by_owner ON categories (owner_user_id);

CREATE TRIGGER categories_fixed_on_update BEFORE UPDATE ON categories WHEN OLD.owner_user_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;

CREATE TRIGGER categories_fixed_on_delete BEFORE DELETE ON categories WHEN OLD.owner_user_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;
