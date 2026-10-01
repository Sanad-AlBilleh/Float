"""Setup, the transaction pages, settings, and the Day 1 dashboard through the browser (FR-05–08, FR-28)."""

from datetime import date

from app.db.connection import connect
from app.ledger.api import create_linked
from tests.web.helpers import (
    add_transaction,
    csrf_from,
    post_form,
    set_up,
    sign_up,
    transaction_ids,
    version_of,
)


def test_new_users_are_sent_to_setup_first(client):
    sign_up(client)
    for path in ("/", "/transactions", "/transactions/new", "/settings"):
        response = client.get(path, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (303, "/setup"), path


def test_setup_explains_what_cannot_change_later(client):
    sign_up(client)
    page = client.get("/setup")
    assert "cannot be changed after setup" in page.text
    assert 'value="2026-09-30"' in page.text  # tracking starts today by default


def test_invalid_setup_keeps_values_and_lists_every_problem(client):
    sign_up(client)
    response = set_up(client, tracking_start="2026-10-01", opening_balance="1,234", allowance_day="40",
                      planned_allowance="0")
    assert response.status_code == 400
    for message in ("Tracking cannot start in the future.", "Use at most two decimal places.",
                    "Choose a day between 1 and 31.", "Enter an amount greater than zero."):
        assert message in response.text
    assert 'value="1,234"' in response.text


def test_setup_leads_to_the_dashboard(client):
    sign_up(client)
    assert set_up(client).status_code == 303
    page = client.get("/")
    assert "€100.00" in page.text and "2026-10-01" in page.text
    assert "No allowance recorded" in page.text
    assert client.get("/setup", follow_redirects=False).headers["location"] == "/"


def test_recording_editing_and_deleting_updates_the_balance(client):
    sign_up(client)
    set_up(client)
    allowance = add_transaction(client, kind="income", amount="750", occurred_on="2026-09-01",
                                income_source="allowance")
    assert (allowance.status_code, allowance.headers["location"]) == (303, "/transactions?saved=1")
    assert "No allowance recorded" not in client.get("/").text
    add_transaction(client, amount="25.40", note="Weekly shop")
    assert "€824.60" in client.get("/").text  # AT-04: €100 + €750 − €25.40
    groceries = transaction_ids(client)[0]
    edited = post_form(client, f"/transactions/{groceries}/edit", f"/transactions/{groceries}/edit",
                       {"kind": "expense", "amount": "30", "occurred_on": "2026-09-20", "category_id": "1",
                        "note": "Weekly shop", "version": version_of(client, groceries)})
    assert edited.status_code == 303 and "€820.00" in client.get("/").text
    deleted = post_form(client, "/transactions", f"/transactions/{groceries}/delete",
                        {"version": version_of(client, groceries)})
    assert deleted.status_code == 303 and "€850.00" in client.get("/").text


def test_a_stale_edit_is_refused(client):
    sign_up(client)
    set_up(client)
    add_transaction(client)
    transaction_id = transaction_ids(client)[0]
    stale = version_of(client, transaction_id)
    form = {"kind": "expense", "amount": "30", "occurred_on": "2026-09-20", "category_id": "1"}
    post_form(client, "/transactions", f"/transactions/{transaction_id}/edit", {**form, "version": stale})
    again = post_form(client, "/transactions", f"/transactions/{transaction_id}/edit", {**form, "version": stale})
    assert again.status_code == 409 and "changed since you opened it" in again.text


def test_invalid_transactions_keep_their_values(client):
    sign_up(client)
    set_up(client)
    response = add_transaction(client, amount="12.345", occurred_on="2026-10-01", note="Too precise")
    assert response.status_code == 400
    assert "Use at most two decimal places." in response.text
    assert "Future transactions cannot be recorded yet." in response.text  # every problem at once
    assert 'value="12.345"' in response.text and "Too precise" in response.text


def test_reloading_after_a_post_never_duplicates(client):
    sign_up(client)
    set_up(client)
    add_transaction(client)
    for _ in range(2):
        client.get("/transactions?saved=1")
    assert len(transaction_ids(client)) == 1


def test_notes_are_escaped(client):
    sign_up(client)
    set_up(client)
    add_transaction(client, note="<script>alert(1)</script>")
    page = client.get("/transactions").text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)" not in page


def test_linked_transactions_show_no_edit_controls(client, settings, clock):
    sign_up(client)
    set_up(client)
    conn = connect(settings.db_path)
    try:
        user_id = conn.execute("SELECT id FROM users WHERE username = 'ana'").fetchone()[0]
        linked = create_linked(conn, user_id=user_id, kind="expense", origin="bill", amount_cents=12000,
                               occurred_on=date(2026, 9, 25), category_id=6, income_source=None,
                               note="Phone", today=clock.today(), now=clock.now_utc())
    finally:
        conn.close()
    page = client.get("/transactions").text
    assert "Managed by its bill" in page and f"/transactions/{linked}/edit" not in page
    assert client.get(f"/transactions/{linked}/edit").status_code == 409


def test_the_planned_allowance_can_be_changed_in_settings(client):
    sign_up(client)
    set_up(client)
    page = client.get("/settings").text
    assert "2026-09-01" in page and "€100.00" in page
    response = post_form(client, "/settings", "/settings/planned-allowance", {"planned_allowance": "800"})
    assert response.status_code == 303
    assert "€800.00" in client.get("/").text


def test_csrf_is_required_for_transactions(client):
    sign_up(client)
    set_up(client)
    token = csrf_from(client.get("/transactions/new"))
    assert token
    response = client.post("/transactions/new", data={"kind": "expense", "amount": "1", "occurred_on": "2026-09-20",
                                                      "category_id": "1"}, follow_redirects=False)
    assert response.status_code == 403
