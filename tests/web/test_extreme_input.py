"""Review finding 5: absurd dates and numbers are refused with a message, never a server error."""

from fastapi.testclient import TestClient

from tests.api.helpers import signed_up
from tests.web.helpers import ORIGIN, csrf_from, post_form, set_up, sign_up


def test_dates_far_outside_a_lifetime_are_refused(client):
    sign_up(client)
    assert set_up(client, tracking_start="0001-01-01").status_code == 400
    set_up(client)
    response = post_form(client, "/goals", "/goals/new", {"name": "Far", "target": "100",
                                                         "target_date": "9999-12-15", "priority": "2"})
    assert response.status_code == 400 and "between 2000-01-01 and 2100-12-31" in response.text
    for path in ("/", "/goals", "/bills", "/forecast", "/alerts"):
        assert client.get(path).status_code == 200, path


def test_huge_ids_and_versions_are_not_found_or_refused(client):
    sign_up(client)
    set_up(client)
    page = post_form(client, "/households", "/households/new", {"name": "Flat"}).headers["location"].split("?")[0]
    token = csrf_from(client.get(page))
    huge = str(2**70)
    remove = client.post(f"{page}/members/{huge}/remove", data={"csrf_token": token}, headers=ORIGIN,
                         follow_redirects=False)
    assert remove.status_code == 404
    transfer = client.post(f"{page}/transfer", data={"csrf_token": token, "version": huge, "new_owner": huge},
                           headers=ORIGIN, follow_redirects=False)
    assert transfer.status_code in (400, 409)


def test_the_api_refuses_extreme_values_with_problem_json(client):
    api = signed_up(client)
    goal = api.post("/goals", {"name": "Far", "target_cents": 100, "target_date": "9999-12-15"})
    assert goal.status_code == 422 and goal.headers["content-type"].startswith("application/problem+json")
    created = api.post("/transactions", {"kind": "expense", "amount_cents": 100, "occurred_on": "2026-09-20",
                                         "category_id": 1}).json()
    stale = api.patch(f"/transactions/{created['id']}", {"version": 2**70, "kind": "expense", "amount_cents": 100,
                                                         "occurred_on": "2026-09-20", "category_id": 1})
    assert stale.status_code == 422


def test_unexpected_api_errors_are_problem_json(app):
    def explode():
        raise RuntimeError("secret internals")

    app.add_api_route("/api/v1/explode", explode)
    with TestClient(app) as browser:
        response = browser.get("/api/v1/explode")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "secret internals" not in response.text and response.json()["request_id"]
