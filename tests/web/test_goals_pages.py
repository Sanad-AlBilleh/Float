"""The goals page through the browser (FR-14)."""

import re

from tests.web.helpers import post_form, set_up, sign_up


def add_goal(client, **fields):
    data = {"name": "Laptop", "target": "600", "target_date": "", "priority": "2"}
    data.update(fields)
    return post_form(client, "/goals", "/goals/new", data)


def goal_id(client) -> str:
    return re.search(r'action="/goals/(\d+)/protect"', client.get("/goals").text).group(1)


def test_goals_can_be_created_protected_released_and_archived(client):
    sign_up(client)
    set_up(client, opening_balance="500")
    assert add_goal(client).status_code == 303
    number = goal_id(client)
    assert post_form(client, "/goals", f"/goals/{number}/protect", {"amount": "50"}).status_code == 303
    page = client.get("/goals").text
    assert "Laptop" in page and "€50.00 of €600.00" in page
    assert "€500.00" in client.get("/").text  # protecting never changes the recorded balance
    assert post_form(client, "/goals", f"/goals/{number}/release", {"amount": "20"}).status_code == 303
    assert "€30.00 of €600.00" in client.get("/goals").text
    too_much = post_form(client, "/goals", f"/goals/{number}/release", {"amount": "31"})
    assert too_much.status_code == 400 and "€30.00" in too_much.text
    version = re.search(r'action="/goals/\d+/archive".*?name="version" value="(\d+)"', client.get("/goals").text,
                        re.S).group(1)
    assert post_form(client, "/goals", f"/goals/{number}/archive", {"version": version}).status_code == 303
    assert "No goals yet." in client.get("/goals").text


def test_an_invalid_goal_keeps_its_values(client):
    sign_up(client)
    set_up(client)
    response = add_goal(client, name="", target="abc", target_date="soon", priority="9")
    assert response.status_code == 400
    for message in ("Enter a name of 1 to 100 characters.", "Enter an amount like 12.50.",
                    "Enter a date as YYYY-MM-DD.", "Choose high, normal, or low priority."):
        assert message in response.text
    assert 'value="abc"' in response.text


def test_a_goal_can_be_edited(client):
    sign_up(client)
    set_up(client)
    add_goal(client)
    number = goal_id(client)
    form = client.get(f"/goals/{number}/edit").text
    version = re.search(r'name="version" value="(\d+)"', form).group(1)
    response = post_form(client, f"/goals/{number}/edit", f"/goals/{number}/edit",
                         {"version": version, "name": "New laptop", "target": "700", "target_date": "2027-03-01",
                          "priority": "1", "auto_reserve": "on"})
    assert response.status_code == 303
    page = client.get("/goals").text
    assert "New laptop" in page and "€700.00" in page and "2027-03-01" in page
