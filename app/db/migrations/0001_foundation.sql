-- Fixed expense categories owned by the Ledger (FR-08). IDs are stable so tests can use them.
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE
) STRICT;

INSERT INTO categories (id, slug, name) VALUES
    (1, 'groceries', 'Groceries'),
    (2, 'eating_out', 'Eating out'),
    (3, 'transport', 'Transport'),
    (4, 'housing', 'Housing'),
    (5, 'utilities', 'Utilities'),
    (6, 'subscriptions', 'Subscriptions'),
    (7, 'study', 'Study'),
    (8, 'leisure', 'Leisure'),
    (9, 'health', 'Health'),
    (10, 'travel', 'Travel'),
    (11, 'other', 'Other');

CREATE TRIGGER categories_fixed_on_update BEFORE UPDATE ON categories
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;

CREATE TRIGGER categories_fixed_on_delete BEFORE DELETE ON categories
BEGIN
    SELECT RAISE(ABORT, 'categories are fixed');
END;
