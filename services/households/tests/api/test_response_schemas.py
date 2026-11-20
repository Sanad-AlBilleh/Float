"""The routes the other API tests do not reach, called once each so their documented response schemas are
checked too (tests/response_schemas.py validates every response the client receives)."""

from tests.api.test_routes import bearer, expense, flat  # noqa: F401  (flat is a fixture)

ANA, BEN = bearer(1), bearer(2)


def test_every_documented_response_matches_what_the_route_returns(client, personal, flat):  # noqa: F811
    base = f"/api/v1/households/{flat}"

    def ok(response, status=200):
        assert response.status_code == status, response.text
        return response.json()

    made = ok(client.post(f"{base}/expenses", json=expense(), headers=ANA), 201)
    ok(client.patch(f"{base}/expenses/{made['id']}", json={**expense(4000), "version": made["version"]}, headers=ANA))

    def settlement():
        return ok(client.post(f"{base}/settlements", json={"payer_user_id": 2, "payee_user_id": 1, "amount_cents": 500,
                                                           "paid_on": "2026-09-21"}, headers=BEN), 201)["settlement"]
    confirmed, rejected, cancelled = settlement(), settlement(), settlement()
    ok(client.post(f"/api/v1/settlements/{confirmed['id']}/confirm", json={"version": confirmed["version"]}, headers=ANA))
    ok(client.post(f"/api/v1/settlements/{rejected['id']}/reject", json={"version": rejected["version"],
                                                                        "reason": "Not yet"}, headers=ANA))
    ok(client.post(f"/api/v1/settlements/{cancelled['id']}/cancel", json={"version": cancelled["version"]}, headers=BEN))
    assert len(ok(client.get(f"{base}/settlements", headers=ANA))) == 3

    ok(client.post(f"{base}/bills", json={"name": "Internet", "amount_cents": 3000, "category_id": 1, "freq": "monthly",
                                          "interval": 1, "anchor_date": "2026-10-05",
                                          "participants": [{"user_id": 1}, {"user_id": 2}]}, headers=ANA), 201)

    def occurrence():
        return ok(client.get(f"{base}/bills", headers=ANA))["occurrences"][0]
    first = occurrence()
    ok(client.patch(f"/api/v1/household-occurrences/{first['id']}", json={
        "version": first["version"], "amount_cents": 3300, "due_date": first["due_date"]}, headers=ANA))
    for action in ("skip", "unskip"):
        ok(client.post(f"/api/v1/household-occurrences/{first['id']}/{action}", json={"version": occurrence()["version"]},
                       headers=ANA))
    ok(client.post(f"/api/v1/household-occurrences/{first['id']}/pay", json={"version": occurrence()["version"]},
                   headers=ANA), 201)
    ok(client.post(f"/api/v1/household-occurrences/{first['id']}/undo", json={"version": occurrence()["version"]},
                   headers=ANA))

    assert ok(client.get(f"{base}/activity", headers=ANA))

    def version():
        return ok(client.get(base, headers=ANA))["household"]["version"]
    ok(client.patch(base, json={"name": "Flat 3C", "version": version()}, headers=ANA))
    ok(client.post(f"{base}/transfer", json={"new_owner_id": 2, "version": version()}, headers=ANA))
    assert ok(client.get(base, headers=BEN))["household"]["name"] == "Flat 3C"

    empty = ok(client.post("/api/v1/households", json={"name": "Old flat"}, headers=ANA), 201)  # nothing to settle
    page = ok(client.post(f"/api/v1/households/{empty['id']}/archive", json={"version": empty["version"]}, headers=ANA))
    assert page["household"]["archived"] is True
