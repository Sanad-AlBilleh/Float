"""The forecast page (FR-30)."""

from tests.web.helpers import add_transaction, post_form, set_up, sign_up


def test_the_forecast_explains_itself_with_text_and_a_chart(client):
    sign_up(client)
    set_up(client, opening_balance="500", tracking_start="2026-09-28", allowance_included="yes")
    post_form(client, "/bills/new", "/bills/new",
              {"name": "Phone", "amount": "120", "category_id": "4", "freq": "monthly", "interval": "1",
               "anchor_date": "2026-10-25", "until": "", "count": ""})
    page = client.get("/forecast").text
    for text in ("Not enough history", "Runway", "Carry-over", "Lowest point", "Next cycle", "<svg",
                 "Expected (with allowance)", "Conservative (no allowance)", "estimate"):
        assert text in page, text


def test_the_pace_appears_after_a_week_of_history(client):
    sign_up(client)
    set_up(client, opening_balance="500", tracking_start="2026-09-01", allowance_included="yes")
    add_transaction(client, amount="56", occurred_on="2026-09-02")
    page = client.get("/forecast").text
    assert "€2.00 per day" in page  # 29 days of history, capped at 28: €56 // 28 days
    assert "Not enough history" not in page
