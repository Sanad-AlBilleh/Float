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


def test_balances_plan_and_settling_up(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_expense(client, page, ids)
    balances = ben.get(page).text
    assert "Ben pays Ana €10.00" in balances and "Carla pays Ana €10.00" in balances
    assert "You owe <strong>€10.00</strong>" in balances
    response = post_form(ben, page + "?tab=settlements", page + "/settlements/new",
                         {"direction": "paid", "counterparty": str(ids[0]), "amount": "10", "paid_on": "2026-09-30"})
    assert response.status_code == 303 and "done=recorded" in response.headers["location"]
    tab = client.get(page + "?tab=settlements").text
    assert "Pending" in tab and "Ben paid Ana" in tab
    confirm = re.search(r'action="(/households/\d+/settlements/\d+/confirm)".*?name="version" value="(\d+)"', tab, re.S)
    assert post_form(client, page + "?tab=settlements", confirm.group(1), {"version": confirm.group(2)}).status_code == 303
    assert "Confirmed" in client.get(page + "?tab=settlements").text
    assert "Ben pays Ana" not in client.get(page).text
    assert "Settlement from Ben" in client.get("/transactions").text


def test_an_invalid_transfer_is_explained(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    response = post_form(ben, page + "?tab=settlements", page + "/settlements/new",
                         {"direction": "paid", "counterparty": str(ids[0]), "amount": "0", "paid_on": "2026-10-05"})
    assert response.status_code == 400
    assert "Enter an amount greater than zero." in response.text


def add_bill(client, page, ids, **fields):
    data = {"name": "Internet", "amount": "36", "category_id": "5", "freq": "monthly", "interval": "1",
            "anchor_date": "2026-09-30", "until": "", "count": "", "split_method": "equal",
            "participant": [str(i) for i in ids]}
    data.update(fields)
    return post_form(client, page + "/bills/new", page + "/bills/new", data)


def test_household_bills_reserve_shares_and_pay_into_balances(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    assert add_bill(client, page, ids).status_code == 303
    tab = ben.get(page + "?tab=bills").text
    assert "Internet" in tab and "€12.00" in tab and "Reserved" in tab
    assert "€488.00" in ben.get("/").text  # €500 − his €12 share, per day with one day left
    pay = re.search(r'action="(/households/\d+/bills/occurrences/\d+/pay)".*?name="version" value="(\d+)"', tab, re.S)
    assert post_form(ben, page + "?tab=bills", pay.group(1), {"version": pay.group(2)}).status_code == 303
    assert "Paid" in client.get(page + "?tab=bills").text
    assert "Ana pays Ben €12.00" in client.get(page).text
    assert "€488.00" in client.get("/").text  # Ana's share became a payable: no change
    undo = re.search(r'action="(/households/\d+/bills/occurrences/\d+/undo)".*?name="version" value="(\d+)"',
                     ben.get(page + "?tab=bills").text, re.S)
    assert post_form(ben, page + "?tab=bills", undo.group(1), {"version": undo.group(2)}).status_code == 303
    assert "Ana pays Ben" not in client.get(page).text


def test_household_bill_rules_through_the_form(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    bad = add_bill(client, page, ids, split_method="exact", anchor_date="2026-09-01", name="")
    assert bad.status_code == 400
    for message in ("Enter a name of 1 to 100 characters.", "Choose a first due date from today on",
                    "Choose equal, percentage, or shares"):
        assert message in bad.text, message
    assert ben.get(page + "/bills/new").status_code == 403


def test_a_participant_can_correct_the_amount_and_the_owner_can_end_it(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_bill(client, page, ids)
    tab = carla.get(page + "?tab=bills").text
    edit = re.search(r'action="(/households/\d+/bills/occurrences/\d+/edit)".*?name="version" value="(\d+)"', tab, re.S)
    assert post_form(carla, page + "?tab=bills", edit.group(1),
                     {"version": edit.group(2), "amount": "45", "due_date": "2026-09-30"}).status_code == 303
    assert "€15.00" in client.get(page + "?tab=bills").text
    end = re.search(r'action="(/households/\d+/bills/\d+/end)".*?name="version" value="(\d+)"',
                    client.get(page + "?tab=bills").text, re.S)
    assert post_form(client, page + "?tab=bills", end.group(1), {"version": end.group(2)}).status_code == 303
    assert "ended" in client.get(page + "?tab=bills").text


def test_former_members_do_not_see_current_balances_or_bills(client, make_client):
    """Review finding 6: after leaving, only history from the membership period is shown."""
    page, ben, carla, ids = flat(client, make_client)
    post_form(ben, page, page + "/leave", {})
    add_expense(client, page, [ids[0], ids[2]], description="Later dinner", amount="40")
    add_bill(client, page, [ids[0], ids[2]], name="Water")
    balances = ben.get(page).text
    assert "only current members" in balances and "Carla pays Ana" not in balances and "€20.00" not in balances
    assert "Water" not in ben.get(page + "?tab=bills").text
    assert "€20.00" not in ben.get(page + "?tab=members").text
    assert "Carla pays Ana €20.00" in client.get(page).text


def test_settlement_notices_read_the_right_way_round(client, make_client):
    """Review findings 7 and 8."""
    page, ben, carla, ids = flat(client, make_client)
    add_expense(client, page, ids)  # Ben and Carla each owe Ana €10
    received = post_form(client, page + "?tab=settlements", page + "/settlements/new",
                         {"direction": "received", "counterparty": str(ids[2]), "amount": "50", "paid_on": "2026-09-30"})
    assert "you will owe them the rest" in client.get(received.headers["location"]).text
    paid = post_form(ben, page + "?tab=settlements", page + "/settlements/new",
                     {"direction": "paid", "counterparty": str(ids[0]), "amount": "50", "paid_on": "2026-09-30"})
    assert "they will owe you the rest" in ben.get(paid.headers["location"]).text
    tab = ben.get(page + "?tab=settlements").text
    cancel = re.search(r'action="(/households/\d+/settlements/\d+/cancel)".*?name="version" value="(\d+)"', tab, re.S)
    done = post_form(ben, page + "?tab=settlements", cancel.group(1), {"version": cancel.group(2)})
    assert "Cancelled." in ben.get(done.headers["location"]).text
