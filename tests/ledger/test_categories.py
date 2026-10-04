"""Custom categories and automatic categorization (student requests, 4 October)."""

import sqlite3

import pytest

from app.ledger.api import category_names, create_category, list_categories, suggest_category
from app.shared.errors import ValidationError
from tests.factories import make_user


def test_users_add_their_own_categories(conn, clock):
    ana, ben = make_user(conn, clock, "ana"), make_user(conn, clock, "ben")
    gym = create_category(conn, user_id=ana.id, name="Gym")
    assert gym.id > 11 and gym.custom
    assert [c.name for c in list_categories(conn, user_id=ana.id)][-1] == "Gym"
    assert "Gym" not in [c.name for c in list_categories(conn, user_id=ben.id)]  # private to Ana
    assert create_category(conn, user_id=ben.id, name="Gym").id != gym.id  # the same name is fine for someone else
    assert category_names(conn)[gym.id] == "Gym"


@pytest.mark.parametrize("name", ["", "x" * 41, "groceries", "GYM"])
def test_names_are_checked(conn, clock, name):
    ana = make_user(conn, clock, "ana")
    create_category(conn, user_id=ana.id, name="Gym")
    with pytest.raises(ValidationError) as error:
        create_category(conn, user_id=ana.id, name=name)
    assert "name" in error.value.errors


def test_the_fixed_categories_stay_fixed(conn, clock):
    with pytest.raises(sqlite3.IntegrityError, match="fixed"):
        conn.execute("UPDATE categories SET name = 'Food' WHERE id = 1")


@pytest.mark.parametrize("text, slug", [
    ("Weekly shop at Mercadona", "groceries"), ("Pizza with friends", "eating_out"), ("Metro card top-up", "transport"),
    ("Rent for October", "housing"), ("Electricity bill", "utilities"), ("Netflix", "subscriptions"),
    ("Statistics textbook", "study"), ("Cinema tickets", "leisure"), ("Pharmacy", "health"),
    ("Flight to Rome", "travel"), ("Something odd", "other"),
])
def test_descriptions_are_categorized(conn, text, slug):
    categories = list_categories(conn)
    assert next(c.slug for c in categories if c.id == suggest_category(text, categories)) == slug


def test_a_custom_category_name_wins(conn, clock):
    ana = make_user(conn, clock, "ana")
    gym = create_category(conn, user_id=ana.id, name="Gym")
    assert suggest_category("Gym membership", list_categories(conn, user_id=ana.id)) == gym.id
