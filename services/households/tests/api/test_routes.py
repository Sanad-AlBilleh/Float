"""The households API over HTTP: bearer tokens checked locally, and the designed failure when the ledger is
down (Assignment 2 §3)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.shared.tokens import sign
from tests.conftest import INTERNAL_KEY, TOKEN_SECRET
from tests.factories import make_member

APP_NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)  # the test clock's 10:00 in Madrid


def bearer(user_id: int, *, secret: str = TOKEN_SECRET, hours: int = 1) -> dict:
    token = sign(secret, user_id=user_id, expires_at=APP_NOW + timedelta(hours=hours))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def flat(client, personal):
    for user_id, name in ((1, "Ana"), (2, "Ben")):
        make_member(personal, user_id, name)
    household = client.post("/api/v1/households", json={"name": "Flat 3B"}, headers=bearer(1)).json()
    code = client.post(f"/api/v1/households/{household['id']}/invitations", headers=bearer(1)).json()["code"]
    assert client.post("/api/v1/households/join", json={"code": code}, headers=bearer(2)).status_code == 200
    return household["id"]


def expense(amount=3000):
    return {"amount_cents": amount, "spent_on": "2026-09-20", "category_id": 1, "description": "Groceries",
            "split_method": "equal", "participants": [{"user_id": 1}, {"user_id": 2}]}


def test_tokens_are_checked_here_without_asking_the_personal_service(client, personal):
    personal.down = True
    assert client.get("/api/v1/households", headers=bearer(1)).status_code == 200
    for headers in ({}, bearer(1, secret="another-secret"), bearer(1, hours=-1)):
        response = client.get("/api/v1/households", headers=headers)
        assert response.status_code == 401 and response.json()["title"] == "Not signed in"


def test_a_shared_expense_records_the_split_and_the_payers_ledger_row(client, personal, flat):
    response = client.post(f"/api/v1/households/{flat}/expenses", json=expense(), headers=bearer(1))
    assert response.status_code == 201 and response.json()["shares"] == {"1": 1500, "2": 1500}
    [row] = personal.ledger(1, "shared")
    assert (row.id, row.amount_cents) == (response.json()["payer_transaction_id"], 3000)
    balances = client.get(f"/api/v1/households/{flat}/balances", headers=bearer(2)).json()
    assert {n["user_id"]: (n["display_name"], n["net_cents"]) for n in balances["nets"]} == {
        1: ("Ana", 1500), 2: ("Ben", -1500)}


def test_names_seen_once_are_still_shown_while_the_ledger_is_down(client, personal, flat):
    """Migration 002: a successful read saves each member's name, and a later read while personal is
    down uses it instead of "Member #id"."""
    assert {m["display_name"] for m in client.get(f"/api/v1/households/{flat}", headers=bearer(1)).json()["members"]} \
        == {"Ana", "Ben"}
    personal.profiles[2] = replace(personal.profiles[2], display_name="BEN")
    client.get(f"/api/v1/households/{flat}", headers=bearer(1))  # a rename in personal, even of case only, replaces the saved name
    personal.down = True
    page = client.get(f"/api/v1/households/{flat}", headers=bearer(1))
    assert page.status_code == 200
    assert {m["display_name"] for m in page.json()["members"]} == {"Ana", "BEN"}


def test_when_the_ledger_is_down_reads_degrade_and_writes_fail_clearly(client, personal, flat):
    client.post(f"/api/v1/households/{flat}/expenses", json=expense(), headers=bearer(1))
    personal.down = True
    page = client.get(f"/api/v1/households/{flat}", headers=bearer(1))
    assert page.status_code == 200  # this service keeps serving its own domain
    assert {m["display_name"] for m in page.json()["members"]} == {"Member #1", "Member #2"}
    refused = client.post(f"/api/v1/households/{flat}/expenses", json=expense(1000), headers=bearer(1))
    assert refused.status_code == 503 and refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json()["title"] == "Ledger unavailable" and "nothing was saved" in refused.json()["detail"]
    personal.down = False
    assert len(client.get(f"/api/v1/households/{flat}/expenses", headers=bearer(1)).json()) == 1


def test_strangers_get_404(client, personal, flat):
    make_member(personal, 9, "Eve")
    for method, path in (("GET", f"/api/v1/households/{flat}"), ("GET", f"/api/v1/households/{flat}/balances"),
                         ("POST", f"/api/v1/households/{flat}/expenses")):
        response = client.request(method, path, json=expense(), headers=bearer(9))
        assert response.status_code == 404, (method, path)


def test_the_internal_api_answers_the_personal_service(client, personal, flat):
    client.post(f"/api/v1/households/{flat}/expenses", json=expense(), headers=bearer(1))
    assert client.get("/internal/users/2/position", params={"window_end": "2026-10-01",
                                                             "horizon_end": "2026-11-01"}).status_code == 401
    key = {"X-Internal-Key": INTERNAL_KEY}
    position = client.get("/internal/users/2/position", params={"window_end": "2026-10-01",
                                                                 "horizon_end": "2026-11-01"}, headers=key).json()
    assert (position["in_household"], position["payables_cents"], position["receivables_cents"]) == (True, 1500, 0)
    shares = client.get("/internal/users/2/shares", params={"start": "2026-09-01", "end": "2026-10-01"},
                        headers=key).json()
    assert shares == [{"amount_cents": 1500, "occurred_on": "2026-09-20", "category_id": 1,
                       "from_household_bill": False, "one_off": False}]
    events = client.get("/internal/users/2/events", params={"after": 0}, headers=key).json()
    assert [(e["actor_user_id"], e["description"], e["share_cents"]) for e in events["expenses"]] == [
        (1, "Groceries", 1500)]
    later = client.get("/internal/users/2/events", params={"after": events["last_id"]}, headers=key).json()
    assert later["expenses"] == [] and later["last_id"] == events["last_id"]
