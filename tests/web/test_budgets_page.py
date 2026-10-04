"""Budgets and unusual-expense flags in the browser (FR-16, FR-31)."""

import re

from tests.web.helpers import add_transaction, post_form, set_up, sign_up


def test_budgets_show_consumption_against_each_limit(client):
    sign_up(client)
    set_up(client, opening_balance="500")
    add_transaction(client, amount="60", category_id="1")
    add_transaction(client, amount="8", category_id="2")
    assert post_form(client, "/budgets", "/budgets/1", {"limit": "50", "scope": "template"}).status_code == 303
    assert post_form(client, "/budgets", "/budgets/2", {"limit": "10", "scope": "cycle"}).status_code == 303
    page = client.get("/budgets").text
    assert "Over by €10.00" in page and "80% used" in page and "No limit" in page
    assert "Every cycle" in page and "This cycle only" in page
    assert post_form(client, "/budgets", "/budgets/1", {"limit": "", "scope": "template"}).status_code == 303
    assert "Over by" not in client.get("/budgets").text


def test_an_invalid_limit_is_explained(client):
    sign_up(client)
    set_up(client)
    response = post_form(client, "/budgets", "/budgets/1", {"limit": "-5", "scope": "template"})
    assert response.status_code == 400 and "Enter a positive amount." in response.text
    assert post_form(client, "/budgets", "/budgets/99", {"limit": "5", "scope": "template"}).status_code == 404


def test_an_unusual_expense_is_flagged_with_a_reason(client):
    sign_up(client)
    set_up(client, opening_balance="500")
    for day, amount in zip(range(2, 10), ("8", "9", "10", "10", "11", "12", "13", "15")):
        add_transaction(client, amount=amount, category_id="2", occurred_on=f"2026-09-{day:02d}")
    add_transaction(client, amount="14", category_id="2", occurred_on="2026-09-20")
    add_transaction(client, amount="13", category_id="2", occurred_on="2026-09-21")
    page = client.get("/transactions").text
    assert page.count("Unusual") == 1
    assert "€14.00 is well above your typical €10.00 for Eating out" in page


def test_goal_plans_are_shown_on_the_goals_page(client):
    sign_up(client)
    set_up(client)
    post_form(client, "/goals", "/goals/new", {"name": "Laptop", "target": "600", "target_date": "2027-03-01",
                                                 "priority": "2", "auto_reserve": "on"})
    page = client.get("/goals").text
    assert "Behind" in page and "€100.00 planned this cycle" in page and "€100.00 still to protect" in page


def test_users_add_categories_and_use_them(client, make_client):
    sign_up(client)
    set_up(client, opening_balance="500")
    assert post_form(client, "/categories", "/categories/new", {"name": "Gym"}).status_code == 303
    page = client.get("/categories").text
    assert "Gym" in page and "Yours" in page
    duplicate = post_form(client, "/categories", "/categories/new", {"name": "groceries"})
    assert duplicate.status_code == 400 and "already have" in duplicate.text
    gym_id = re.search(r'<option value="(\d+)"[^>]*>Gym</option>', client.get("/transactions/new").text).group(1)
    assert add_transaction(client, amount="30", category_id=gym_id, note="Monthly gym").status_code == 303
    assert "Gym" in client.get("/budgets").text
    other = make_client()
    sign_up(other, "eve", "Eve")
    set_up(other)
    assert ">Gym</span>" not in other.get("/categories").text
    assert add_transaction(other, amount="5", category_id=gym_id).status_code == 400  # not Eve's category
