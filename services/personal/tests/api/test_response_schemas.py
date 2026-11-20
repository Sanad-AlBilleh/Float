"""The routes the other API tests do not reach, called once each so their documented response schemas are
checked too (tests/response_schemas.py validates every response the client receives)."""

from tests.api.helpers import signed_up


def test_every_documented_response_matches_what_the_route_returns(client):
    ana = signed_up(client)
    assert ana.get("/me").json()["setup_complete"] is True
    assert ana.get("/settings").status_code == 200
    assert ana.patch("/settings", {"planned_allowance_cents": 80000}).status_code == 200

    goal = ana.post("/goals", {"name": "Car", "target_cents": 1000}).json()
    edited = ana.patch(f"/goals/{goal['id']}", {"name": "Bike", "target_cents": 2000, "version": goal["version"]})
    assert edited.status_code == 200 and edited.json()["name"] == "Bike"

    bill = ana.post("/bills", {"name": "Phone", "amount_cents": 1000, "category_id": 4, "freq": "monthly",
                               "interval": 1, "anchor_date": "2026-09-25"}).json()
    assert [series["id"] for series in ana.get("/bills").json()] == [bill["id"]]

    def first_occurrence():
        return ana.get("/occurrences").json()[0]

    occurrence = first_occurrence()
    moved = ana.patch(f"/occurrences/{occurrence['id']}", {"version": occurrence["version"], "amount_cents": 1200,
                                                           "due_date": occurrence["due_date"]})
    assert moved.status_code == 200 and moved.json()["amount_cents"] == 1200
    for action in ("skip", "unskip"):
        response = ana.post(f"/occurrences/{occurrence['id']}/{action}", {"version": first_occurrence()["version"]})
        assert response.status_code == 200, response.text
    paid = ana.post(f"/occurrences/{occurrence['id']}/pay", {"version": first_occurrence()["version"]})
    assert paid.status_code == 201, paid.text
    undone = ana.post(f"/occurrences/{occurrence['id']}/undo", {"version": paid.json()["occurrence"]["version"]})
    assert undone.status_code == 200, undone.text

    later = ana.get("/occurrences").json()[1]
    split = ana.post(f"/occurrences/{later['id']}/split", {"version": later["version"], "name": "Phone (new plan)",
                                                           "amount_cents": 1500, "category_id": 4, "freq": "monthly",
                                                           "interval": 1, "anchor_date": later["scheduled_date"]})
    assert split.status_code == 201, split.text
    ended = ana.post(f"/bills/{split.json()['id']}/end", {"version": split.json()["version"]})
    assert ended.status_code == 200 and ended.json()["ended"] is True

