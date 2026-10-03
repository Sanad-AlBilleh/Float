"""The JSON API exposes the same use cases as the pages (FR-34, AT-26)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import connect
from app.main import create_app
from tests.api.helpers import PASSWORD, Api, signed_up
from tests.scenarios.flat_3b import build_flat_3b, fixture_a_clock


@pytest.fixture
def fixture_a(tmp_path):
    clock = fixture_a_clock()
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, clock)
    conn = connect(settings.db_path)
    try:
        flat = build_flat_3b(conn, clock)
    finally:
        conn.close()
    with TestClient(app) as browser:
        api = Api(browser)
        assert api.post("/auth/login", {"username": "ana", "password": PASSWORD}).status_code == 200
        yield api, flat


def test_the_dashboard_matches_fixture_a(fixture_a):
    api, _ = fixture_a
    data = api.get("/dashboard").json()
    assert data["discretionary_cents"] == 30800 and data["discretionary_display"] == "€308.00"
    assert (data["daily_cents"], data["days_remaining"]) == (2800, 11)
    terms = data["terms"]
    assert (terms["recorded_balance_cents"], terms["personal_bills_cents"], terms["household_bill_shares_cents"],
            terms["protected_savings_cents"], terms["household_payables_cents"]) == (50000, 12000, 1200, 5000, 1000)
    assert api.get("/dashboard/preview", params={"cost": "350"}).json()["after_shortfall_cents"] == 4200


def test_the_forecast_and_balances_match_fixture_a(fixture_a):
    api, flat = fixture_a
    forecast = api.get("/forecast").json()
    assert (forecast["pace_cents"], forecast["runway_days"], forecast["next_daily_cents"]) == (1200, 25, 2561)
    balances = api.get(f"/households/{flat.household_id}/balances").json()
    assert {row["user_id"]: row["net_cents"] for row in balances["nets"]} == {
        flat.ana.user_id: -1000, flat.ben.user_id: 5000, flat.carla.user_id: -4000}
    assert balances["plan"][0] == {"from_user": flat.carla.user_id, "to_user": flat.ben.user_id,
                                   "amount_cents": 4000, "amount_display": "€40.00"}


def test_paying_a_bill_through_the_api(fixture_a):
    api, flat = fixture_a
    occurrences = api.get("/occurrences").json()
    phone = next(o for o in occurrences if o["id"] == flat.phone_occurrence_id)
    paid = api.post(f"/occurrences/{phone['id']}/pay", {"version": phone["version"], "paid_on": "2026-09-20"})
    assert paid.status_code == 201
    assert api.get("/dashboard").json()["discretionary_cents"] == 30800
    again = api.post(f"/occurrences/{phone['id']}/pay", {"version": phone["version"], "paid_on": "2026-09-20"})
    assert again.status_code == 409 and again.headers["content-type"].startswith("application/problem+json")


def test_transactions_round_trip(client):
    api = signed_up(client)
    created = api.post("/transactions", {"kind": "expense", "amount_cents": 1250, "occurred_on": "2026-09-20",
                                         "category_id": 1, "note": "Lunch"})
    assert created.status_code == 201
    body = created.json()
    assert (body["amount_cents"], body["amount_display"]) == (1250, "€12.50")
    edited = api.patch(f"/transactions/{body['id']}", {"version": body["version"], "kind": "expense",
                                                       "amount_cents": 1300, "occurred_on": "2026-09-20",
                                                       "category_id": 1})
    assert edited.json()["amount_cents"] == 1300
    stale = api.patch(f"/transactions/{body['id']}", {"version": body["version"], "kind": "expense",
                                                      "amount_cents": 1400, "occurred_on": "2026-09-20",
                                                      "category_id": 1})
    assert stale.status_code == 409
    assert api.delete(f"/transactions/{body['id']}", {"version": edited.json()["version"]}).status_code == 204
    assert api.get("/transactions").json() == []


def test_validation_errors_are_problem_json_with_fields(client):
    api = signed_up(client)
    response = api.post("/transactions", {"kind": "expense", "amount_cents": 0, "occurred_on": "2026-10-05",
                                          "category_id": 99})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert {"amount", "occurred_on", "category_id"} <= set(response.json()["errors"])
    malformed = api.post("/transactions", {"kind": "expense", "amount_cents": "lots"})
    assert malformed.status_code == 422 and "errors" in malformed.json()


def test_unsafe_requests_need_the_csrf_header(client):
    api = signed_up(client)
    response = client.post("/api/v1/transactions", json={"kind": "expense", "amount_cents": 100,
                                                          "occurred_on": "2026-09-20", "category_id": 1})
    assert response.status_code == 403 and response.json()["title"] == "Request blocked"


def test_anonymous_requests_get_401(make_client):
    anonymous = make_client()
    response = anonymous.get("/api/v1/dashboard")
    assert response.status_code == 401 and response.headers["content-type"].startswith("application/problem+json")


def test_households_goals_budgets_and_alerts(client, make_client):
    ana = signed_up(client)
    ben = signed_up(make_client(), "ben")
    household = ana.post("/households", {"name": "Flat 3B"}).json()
    code = ana.post(f"/households/{household['id']}/invitations").json()["code"]
    assert ben.post("/households/join", {"code": code}).status_code == 200
    members = ana.get(f"/households/{household['id']}").json()["members"]
    ids = [m["user_id"] for m in members]
    expense = ana.post(f"/households/{household['id']}/expenses", {
        "amount_cents": 3000, "spent_on": "2026-09-20", "category_id": 1, "description": "Groceries",
        "split_method": "equal", "participants": [{"user_id": i} for i in ids]})
    assert expense.status_code == 201 and expense.json()["shares"] == {str(i): 1500 for i in ids}
    settlement = ben.post(f"/households/{household['id']}/settlements", {
        "payer_user_id": ids[1], "payee_user_id": ids[0], "amount_cents": 1500, "paid_on": "2026-09-20"})
    assert settlement.status_code == 201
    sid = settlement.json()["settlement"]["id"]
    confirmed = ana.post(f"/settlements/{sid}/confirm", {"version": settlement.json()["settlement"]["version"]})
    assert confirmed.json()["status"] == "confirmed"
    goal = ana.post("/goals", {"name": "Laptop", "target_cents": 60000})
    assert ana.post(f"/goals/{goal.json()['id']}/movements", {"delta_cents": 5000}).json()["protected_cents"] == 5000
    assert ana.put("/budgets/1", {"limit_cents": 1000, "scope": "template"}).status_code == 200
    budgets = {row["category_id"]: row for row in ana.get("/budgets").json()}
    assert budgets[1]["state"] == "over"
    assert any(a["type"] == "BUDGET_OVER" for a in ana.get("/alerts").json())
    assert ana.get(f"/households/{household['id']}/activity").json()
