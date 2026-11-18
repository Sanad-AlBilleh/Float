"""The JSON API exposes the A1 use cases (FR-34, AT-26), now with Fixture A's household terms coming from
the (scripted) households service."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.helpers import PASSWORD, Api, signed_up
from tests.scenarios.flat_3b import build_flat_3b, fixture_a_clock


@pytest.fixture
def fixture_a(conn, settings):
    clock = fixture_a_clock()
    flat = build_flat_3b(conn, clock)
    app = create_app(settings, clock, households=flat.households, run_migrations=False)
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


def test_the_forecast_matches_fixture_a(fixture_a):
    api, _ = fixture_a
    forecast = api.get("/forecast").json()
    assert (forecast["pace_cents"], forecast["runway_days"], forecast["next_daily_cents"]) == (1200, 25, 2561)


def test_the_dashboard_still_answers_when_the_households_service_is_down(fixture_a):
    api, flat = fixture_a
    flat.households.down = True
    data = api.get("/dashboard").json()
    assert data["households_available"] is False and data["terms"]["household_payables_cents"] == 0


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


def test_setup_takes_monthly_savings_like_the_form(client):
    api = signed_up(client, setup=False)
    body = {"tracking_start": "2026-09-01", "opening_balance_cents": 50000, "allowance_day": 1}
    refused = api.post("/setup", {**body, "monthly_savings_cents": -100})
    assert refused.status_code == 422 and "monthly_savings" in refused.json()["errors"]
    assert api.post("/setup", {**body, "monthly_savings_cents": 10000}).status_code == 200
    [goal] = api.get("/goals").json()
    assert (goal["name"], goal["target_cents"], goal["auto_reserve"]) == ("Monthly savings", 120000, True)


def test_an_expense_without_a_category_gets_one_from_its_note(client):
    api = signed_up(client)
    created = api.post("/transactions", {"kind": "expense", "amount_cents": 850, "occurred_on": "2026-09-20",
                                         "note": "Pizza with friends"})
    assert created.status_code == 201 and created.json()["category_id"] == 2  # Eating out, as the form picks
    silent = api.post("/transactions", {"kind": "expense", "amount_cents": 850, "occurred_on": "2026-09-20"})
    assert silent.status_code == 422 and "note" in silent.json()["errors"]


def test_validation_errors_are_problem_json_with_fields(client):
    api = signed_up(client)
    response = api.post("/transactions", {"kind": "expense", "amount_cents": 0, "occurred_on": "2026-10-05",
                                          "category_id": 99})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert {"amount", "occurred_on", "category_id"} <= set(response.json()["errors"])
    malformed = api.post("/transactions", {"kind": "expense", "amount_cents": "lots"})
    assert malformed.status_code == 422 and "errors" in malformed.json()


def test_anonymous_requests_get_401(make_client):
    anonymous = make_client()
    response = anonymous.get("/api/v1/dashboard")
    assert response.status_code == 401 and response.headers["content-type"].startswith("application/problem+json")


def test_goals_budgets_and_alerts(client):
    ana = signed_up(client)
    assert ana.post("/transactions", {"kind": "expense", "amount_cents": 1500, "occurred_on": "2026-09-20",
                                      "category_id": 1}).status_code == 201
    goal = ana.post("/goals", {"name": "Laptop", "target_cents": 60000})
    assert ana.post(f"/goals/{goal.json()['id']}/movements", {"delta_cents": 5000}).json()["protected_cents"] == 5000
    assert ana.put("/budgets/1", {"limit_cents": 1000, "scope": "template"}).status_code == 200
    budgets = {row["category_id"]: row for row in ana.get("/budgets").json()}
    assert budgets[1]["state"] == "over"
    assert any(a["type"] == "BUDGET_OVER" for a in ana.get("/alerts").json())
    assert ana.get("/activity").json()


def test_categories_are_listed_for_the_forms(client):
    api = signed_up(client)
    rows = api.get("/categories").json()
    assert [(c["id"], c["name"]) for c in rows[:2]] == [(1, "Groceries"), (2, "Eating out")] and len(rows) == 11
