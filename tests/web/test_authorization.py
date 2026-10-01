"""AT-03 authorization matrix: other people's records answer 404; anonymous visitors go to login.

Each build day adds rows for its new routes.
"""

import pytest

from tests.web.helpers import add_transaction, csrf_from, set_up, sign_up, transaction_ids, version_of


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
    assert ben.post(f"/transactions/{transaction_id}/edit", data=form, follow_redirects=False).status_code == 404
    assert ben.post(f"/transactions/{transaction_id}/delete", data=form, follow_redirects=False).status_code == 404
    assert "Ana's groceries" not in ben.get("/transactions").text
    assert "Ana&#39;s groceries" in client.get("/transactions").text  # untouched for its owner


@pytest.mark.parametrize("path", ["/", "/transactions", "/transactions/new", "/transactions/1/edit", "/setup",
                                  "/settings", "/account"])
def test_anonymous_visitors_are_sent_to_login(make_client, path):
    anonymous = make_client()
    response = anonymous.get(path, follow_redirects=False)
    if path == "/":
        assert response.status_code == 200 and "Create an account" in response.text
    else:
        assert response.status_code == 303 and response.headers["location"].startswith("/login?next=")
