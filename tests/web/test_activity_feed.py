"""The alert centre and the activity feeds through the browser (FR-32, FR-33, AT-24)."""

import re

from tests.web.helpers import ORIGIN, add_transaction, csrf_from, post_form, set_up, sign_up
from tests.web.test_household_money_pages import add_expense, flat


def test_the_alert_centre_lists_reads_and_dismisses(client):
    sign_up(client)
    set_up(client)
    page = client.get("/alerts").text
    assert "No allowance recorded this cycle" in page
    alert_id = re.search(r'action="/alerts/(\d+)/read"', page).group(1)
    assert post_form(client, "/alerts", f"/alerts/{alert_id}/read", {}).status_code == 303
    assert post_form(client, "/alerts", f"/alerts/{alert_id}/dismiss", {}).status_code == 303
    assert "No allowance recorded this cycle" not in client.get("/alerts").text


def test_alerts_follow_a_successful_post(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_expense(ben, page, ids, description="Pizza night")
    assert "Pizza night" in client.get("/alerts").text
    assert "Pizza night" not in ben.get("/alerts").text


def test_someone_elses_alert_is_not_found(client, make_client):
    sign_up(client)
    set_up(client)
    alert_id = re.search(r'action="/alerts/(\d+)/read"', client.get("/alerts").text).group(1)
    eve = make_client()
    sign_up(eve, "eve", "Eve")
    set_up(eve)
    token = csrf_from(eve.get("/alerts"))
    for action in ("read", "dismiss"):
        response = eve.post(f"/alerts/{alert_id}/{action}", data={"csrf_token": token}, headers=ORIGIN,
                            follow_redirects=False)
        assert response.status_code == 404


def test_the_household_activity_feed_is_for_members(client, make_client):
    page, ben, carla, ids = flat(client, make_client)
    add_expense(client, page, ids)
    feed = ben.get(page + "?tab=activity").text
    assert "Ana added the shared expense “Groceries” (€30.00)" in feed
    assert "Ben joined the household" in feed


def test_personal_activity_is_private(client, make_client):
    sign_up(client)
    set_up(client)
    add_transaction(client, amount="12.34", note="secret snack")
    mine = client.get("/activity").text
    assert "You added an expense of €12.34" in mine
    eve = make_client()
    sign_up(eve, "eve", "Eve")
    set_up(eve)
    assert "€12.34" not in eve.get("/activity").text


def test_former_members_do_not_see_later_activity(client, make_client, clock):
    page, ben, carla, ids = flat(client, make_client)
    post_form(ben, page, page + "/leave", {})
    clock.advance(minutes=5)
    add_expense(client, page, [ids[0], ids[2]], description="After Ben left")
    assert "After Ben left" in client.get(page + "?tab=activity").text
    assert "After Ben left" not in ben.get(page + "?tab=activity").text
    assert "Ben left the household" in ben.get(page + "?tab=activity").text


def test_alerts_are_refreshed_right_after_a_post(client, settings):
    from app.db.connection import connect

    sign_up(client)
    set_up(client)
    post_form(client, "/budgets", "/budgets/1", {"limit": "5", "scope": "template"})
    add_transaction(client, amount="6", category_id="1")  # no page is loaded after this post
    conn = connect(settings.db_path)
    try:
        types = {row[0] for row in conn.execute("SELECT type FROM alerts WHERE resolved_at IS NULL")}
    finally:
        conn.close()
    assert "BUDGET_OVER" in types
