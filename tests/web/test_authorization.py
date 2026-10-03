"""AT-03 authorization matrix: other people's records answer 404; anonymous visitors go to login.

Each build day adds rows for its new routes.
"""

import re

import pytest

from tests.web.helpers import (
    ORIGIN,
    add_transaction,
    csrf_from,
    post_form,
    set_up,
    sign_up,
    transaction_ids,
    version_of,
)


@pytest.fixture
def anas_transaction(client):
    sign_up(client, "ana")
    set_up(client)
    add_transaction(client, note="Ana's groceries")
    transaction_id = transaction_ids(client)[0]
    return transaction_id, version_of(client, transaction_id)


@pytest.fixture
def ben(make_client):
    browser = make_client()
    sign_up(browser, "ben", "Ben")
    set_up(browser)
    return browser


def test_another_users_transaction_is_not_found(client, anas_transaction, ben):
    transaction_id, version = anas_transaction
    token = csrf_from(ben.get("/transactions/new"))
    form = {"kind": "expense", "amount": "1", "occurred_on": "2026-09-20", "category_id": "1",
            "version": version, "csrf_token": token}
    assert ben.get(f"/transactions/{transaction_id}/edit").status_code == 404
    edit = ben.post(f"/transactions/{transaction_id}/edit", data=form, headers=ORIGIN, follow_redirects=False)
    delete = ben.post(f"/transactions/{transaction_id}/delete", data=form, headers=ORIGIN, follow_redirects=False)
    assert edit.status_code == delete.status_code == 404
    assert "Ana's groceries" not in ben.get("/transactions").text
    assert "Ana&#39;s groceries" in client.get("/transactions").text  # untouched for its owner


@pytest.mark.parametrize("path", ["/", "/transactions", "/transactions/new", "/transactions/1/edit", "/setup",
                                  "/bills", "/bills/new", "/bills/occurrences/1", "/goals", "/goals/1/edit", "/forecast", "/budgets", "/households", "/households/1", "/alerts", "/activity",
                                  "/settings", "/account"])
def test_anonymous_visitors_are_sent_to_login(make_client, path):
    anonymous = make_client()
    response = anonymous.get(path, follow_redirects=False)
    if path == "/":
        assert response.status_code == 200 and "Create an account" in response.text
    else:
        assert response.status_code == 303 and response.headers["location"].startswith("/login?next=")


def test_another_users_bills_are_not_found(client, ben):
    sign_up(client, "ana")
    set_up(client)
    post_form(client, "/bills/new", "/bills/new",
              {"name": "Ana's phone", "amount": "120", "category_id": "4", "freq": "monthly", "interval": "1",
               "anchor_date": "2026-09-25", "until": "", "count": ""})
    page = client.get("/bills").text
    occurrence_id = re.search(r'/bills/occurrences/(\d+)', page).group(1)
    series_id = re.search(r'/bills/series/(\d+)/end', page).group(1)
    token = csrf_from(ben.get("/bills"))
    assert ben.get(f"/bills/occurrences/{occurrence_id}").status_code == 404
    for action in ("pay", "undo", "skip", "unskip", "edit", "split"):
        response = ben.post(f"/bills/occurrences/{occurrence_id}/{action}",
                            data={"csrf_token": token, "version": "1"}, headers=ORIGIN, follow_redirects=False)
        assert response.status_code == 404, action
    end = ben.post(f"/bills/series/{series_id}/end", data={"csrf_token": token, "version": "1"}, headers=ORIGIN,
                   follow_redirects=False)
    assert end.status_code == 404
    assert "Ana&#39;s phone" not in ben.get("/bills").text


def test_another_users_goals_are_not_found(client, ben):
    sign_up(client, "ana")
    set_up(client)
    post_form(client, "/goals", "/goals/new", {"name": "Ana's laptop", "target": "600", "priority": "2"})
    goal_id = re.search(r'action="/goals/(\d+)/protect"', client.get("/goals").text).group(1)
    token = csrf_from(ben.get("/goals"))
    assert ben.get(f"/goals/{goal_id}/edit").status_code == 404
    for action in ("protect", "release", "archive", "edit"):
        response = ben.post(f"/goals/{goal_id}/{action}", data={"csrf_token": token, "version": "1", "amount": "1"},
                            headers=ORIGIN, follow_redirects=False)
        assert response.status_code == 404, action
    assert "Ana&#39;s laptop" not in ben.get("/goals").text


def test_household_routes_are_hidden_from_non_members(client, ben):
    sign_up(client, "ana")
    set_up(client)
    page = post_form(client, "/households", "/households/new", {"name": "Ana's flat"}).headers["location"].split("?")[0]
    token = csrf_from(ben.get("/households"))
    assert ben.get(page).status_code == 404
    for action in ("invitations", "invitations/1/revoke", "leave", "members/1/remove", "transfer", "rename",
                   "archive", "expenses/new", "settlements/new", "bills/new"):
        response = ben.post(f"{page}/{action}", data={"csrf_token": token, "version": "1"}, headers=ORIGIN,
                            follow_redirects=False)
        assert response.status_code == 404, action
