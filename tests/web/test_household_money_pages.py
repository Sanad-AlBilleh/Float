"""Shared expenses, balances, settlements, and household bills through the browser (FR-20–26)."""

import re

from tests.web.helpers import post_form, set_up, sign_up

CODE = re.compile(r'<code class="invite-code">([0-9A-Z]{10})</code>')


def person(make_client, username):
    browser = make_client()
    sign_up(browser, username, username.title())
    set_up(browser, opening_balance="500")
    return browser


def flat(client, make_client):
    """Ana (client) owns Flat 3B; Ben and Carla joined. Returns the page URL, the browsers, and user IDs."""
    sign_up(client)
    set_up(client, opening_balance="500")
    page = post_form(client, "/households", "/households/new", {"name": "Flat 3B"}).headers["location"].split("?")[0]
    others = []
    for name in ("ben", "carla"):
        browser = person(make_client, name)
        code = CODE.search(post_form(client, page + "?tab=members", page + "/invitations", {}).text).group(1)
        post_form(browser, "/households", "/households/join", {"code": code})
        others.append(browser)
    ids = [int(value) for value in re.findall(r'name="participant" value="(\d+)"', client.get(page + "/expenses/new").text)]
    return page, others[0], others[1], ids


def add_expense(browser, page, ids, **fields):
    data = {"amount": "30", "spent_on": "2026-09-19", "category_id": "1", "description": "Groceries",
            "split_method": "equal", "participant": [str(i) for i in ids]}
    data.update(fields)
    return post_form(browser, page + "/expenses/new", page + "/expenses/new", data)


def test_recording_a_shared_expense(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    assert add_expense(client, page, ids).status_code == 303
    expenses = client.get(page + "?tab=expenses").text
    assert "Groceries" in expenses and "€30.00" in expenses and "€10.00" in expenses
    assert "Managed by its shared expense" in client.get("/transactions").text


def test_split_methods_through_the_form(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    weights = {f"value_{ids[0]}": "2", f"value_{ids[1]}": "1", f"value_{ids[2]}": "1"}
    assert add_expense(client, page, ids, amount="10.01", split_method="shares", **weights).status_code == 303
    assert "€5.01" in client.get(page + "?tab=expenses").text
    bad = add_expense(client, page, ids, split_method="percentage",
                      **{f"value_{ids[0]}": "50", f"value_{ids[1]}": "49.99", f"value_{ids[2]}": "0"})
    assert bad.status_code == 400 and "Percentages must add up to exactly 100%." in bad.text
    exact = add_expense(client, page, ids, amount="100", split_method="exact",
                        **{f"value_{ids[0]}": "40", f"value_{ids[1]}": "35", f"value_{ids[2]}": "24.99"})
    assert exact.status_code == 400 and "€99.99" in exact.text
    none = add_expense(client, page, [], description="")
    assert none.status_code == 400 and "Describe it" in none.text and "participant" in none.text.lower()


def test_only_the_payer_may_edit_and_edits_follow_through(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_expense(client, page, ids)
    tab = client.get(page + "?tab=expenses").text
    edit_url = re.search(r'href="(/households/\d+/expenses/\d+/edit)"', tab).group(1)
    assert ben.get(edit_url).status_code == 403
    form = client.get(edit_url).text
    version = re.search(r'name="version" value="(\d+)"', form).group(1)
    response = post_form(client, edit_url, edit_url, {
        "version": version, "amount": "45", "spent_on": "2026-09-19", "category_id": "1", "description": "Big shop",
        "split_method": "equal", "participant": [str(i) for i in ids]})
    assert response.status_code == 303
    assert "€15.00" in client.get(page + "?tab=expenses").text
    stale = post_form(client, edit_url, edit_url, {
        "version": version, "amount": "60", "spent_on": "2026-09-19", "category_id": "1", "description": "Again",
        "split_method": "equal", "participant": [str(i) for i in ids]})
    assert stale.status_code == 409 and "Big shop" in stale.text
    delete_url = edit_url.replace("/edit", "/delete")
    version = re.search(r'name="version" value="(\d+)"', client.get(edit_url).text).group(1)
    assert post_form(client, page + "?tab=expenses", delete_url, {"version": version}).status_code == 303
    assert "Big shop" not in client.get(page + "?tab=expenses").text


def test_former_members_see_only_their_own_period(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_expense(client, page, [ids[0], ids[2]], description="Before Ben joined", spent_on="2026-09-10")
    add_expense(client, page, [ids[0], ids[2]], description="While Ben was here", spent_on="2026-09-30")
    post_form(ben, page, page + "/leave", {})
    history = ben.get(page + "?tab=expenses").text
    assert "While Ben was here" in history and "Before Ben joined" not in history
    assert "Before Ben joined" in client.get(page + "?tab=expenses").text
