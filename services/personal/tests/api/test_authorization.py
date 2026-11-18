"""The API's authorization matrix: other people's records are 404 (AT-03, AT-26). Household records are
checked the same way in the households service's tests."""

from tests.api.helpers import signed_up


def test_other_peoples_records_are_not_found(client, make_client):
    ana = signed_up(client)
    eve = signed_up(make_client(), "eve")
    transaction = ana.post("/transactions", {"kind": "expense", "amount_cents": 100, "occurred_on": "2026-09-20",
                                             "category_id": 1}).json()
    bill = ana.post("/bills", {"name": "Phone", "amount_cents": 1000, "category_id": 4, "freq": "monthly",
                               "interval": 1, "anchor_date": "2026-09-25"}).json()
    occurrence = ana.get("/occurrences").json()[0]
    goal = ana.post("/goals", {"name": "Car", "target_cents": 1000}).json()
    alert = ana.get("/alerts").json()[0]
    for method, path in [
        ("GET", f"/transactions/{transaction['id']}"), ("PATCH", f"/transactions/{transaction['id']}"),
        ("DELETE", f"/transactions/{transaction['id']}"), ("POST", f"/bills/{bill['id']}/end"),
        ("PATCH", f"/occurrences/{occurrence['id']}"), ("POST", f"/occurrences/{occurrence['id']}/pay"),
        ("PATCH", f"/goals/{goal['id']}"), ("POST", f"/goals/{goal['id']}/movements"),
        ("POST", f"/alerts/{alert['id']}/read"),
    ]:
        response = eve.send(method, path, {"version": 1}) if method != "GET" else eve.get(path)
        assert response.status_code == 404, (method, path, response.status_code)
