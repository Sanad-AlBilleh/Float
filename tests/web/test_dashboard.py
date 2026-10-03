"""The dashboard's breakdown, shortfall, and read-only purchase preview (FR-27–29, AT-19)."""

from app.db.connection import connect
from tests.web.helpers import post_form, set_up, sign_up


def snapshot(settings) -> dict[str, list[tuple]]:
    conn = connect(settings.db_path)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in tables}
    finally:
        conn.close()


def ready(client):
    sign_up(client)
    set_up(client, opening_balance="500", allowance_included="yes")
    post_form(client, "/bills/new", "/bills/new",
              {"name": "Phone", "amount": "120", "category_id": "4", "freq": "monthly", "interval": "1",
               "anchor_date": "2026-09-30", "until": "", "count": ""})


def test_the_dashboard_shows_every_term_with_links(client):
    ready(client)
    page = client.get("/").text
    for text in ("Safe to spend today", "€380.00", "Bills due before", "€120.00", "Protected savings",
                 "Household bill shares", "What you owe flatmates", "Goal plan reserve", 'href="/bills"',
                 'href="/goals"', 'href="/transactions"'):
        assert text in page, text
    assert "per day" in page


def test_a_shortfall_is_shown_in_words(client):
    ready(client)
    post_form(client, "/goals", "/goals/new", {"name": "Car", "target": "2000", "priority": "2"})
    page = client.get("/goals").text
    import re
    goal_id = re.search(r'action="/goals/(\d+)/protect"', page).group(1)
    post_form(client, "/goals", f"/goals/{goal_id}/protect", {"amount": "400"})
    page = client.get("/").text
    assert "Shortfall" in page and "€20.00" in page and "€0.00 per day" in page


def test_a_preview_reports_the_result_and_writes_nothing(client, settings):
    ready(client)
    client.get("/")
    before = snapshot(settings)
    page = client.get("/?cost=110").text
    assert "€270.00" in page and "€270.00 per day" in page  # one day left in the cycle
    big = client.get("/?cost=400").text
    assert "€20.00 short" in big
    assert snapshot(settings) == before


def test_an_invalid_preview_cost_is_explained(client):
    ready(client)
    response = client.get("/?cost=abc")
    assert response.status_code == 400 and "Enter an amount like 12.50." in response.text
    assert 'value="abc"' in response.text
