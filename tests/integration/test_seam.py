"""Cross-seam integration test against the running compose stack (Assignment 2 §5, ADR-9).

Both real services and the real SQL Server, nothing stubbed: a flow that crosses the seam on the server
(a shared expense recorded by households lands in the payer's ledger in personal; the flatmate's dashboard
in personal shows what they owe), then each service is stopped in turn to check the designed partial
failure: the other keeps serving its own domain, and the cross-seam action fails quickly and clearly.

Run with the stack up:  docker compose up -d --build --wait  then  pytest tests/integration
"""

import os
import subprocess
import time
import uuid
from datetime import date

import httpx2 as httpx
import pytest

PERSONAL = os.environ.get("PERSONAL_URL", "http://localhost:8001")
HOUSEHOLDS = os.environ.get("HOUSEHOLDS_URL", "http://localhost:8002")
TODAY = date.today().isoformat()
FIRST_OF_MONTH = date.today().replace(day=1).isoformat()


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def wait_healthy(base: str, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise AssertionError(f"{base} did not become healthy")


class User:
    def __init__(self, name: str):
        self.username = f"{name}{uuid.uuid4().hex[:8]}"
        response = httpx.post(f"{PERSONAL}/api/v1/auth/register", timeout=10, json={
            "username": self.username, "display_name": name.title(), "password": "integration test passphrase"})
        assert response.status_code == 201, response.text
        self.id = response.json()["user"]["id"]
        self.headers = {"Authorization": f"Bearer {response.json()['token']}"}
        setup = self.call("POST", PERSONAL, "/setup", {"tracking_start": FIRST_OF_MONTH, "opening_balance_cents": 50000,
                                                        "allowance_day": 1, "allowance_included": True})
        assert setup.status_code == 200, setup.text

    def call(self, method: str, base: str, path: str, body=None, timeout: float = 10):
        return httpx.request(method, f"{base}/api/v1{path}", json=body, headers=self.headers, timeout=timeout)


@pytest.fixture(scope="module")
def flat():
    wait_healthy(PERSONAL)
    wait_healthy(HOUSEHOLDS)
    ana, ben = User("ana"), User("ben")
    household = ana.call("POST", HOUSEHOLDS, "/households", {"name": "Integration flat"}).json()
    code = ana.call("POST", HOUSEHOLDS, f"/households/{household['id']}/invitations").json()["code"]
    assert ben.call("POST", HOUSEHOLDS, "/households/join", {"code": code}).status_code == 200
    return household["id"], ana, ben


def expense(ana, ben, amount=3000):
    return {"amount_cents": amount, "spent_on": TODAY, "category_id": 1, "description": "Groceries",
            "split_method": "equal", "participants": [{"user_id": ana.id}, {"user_id": ben.id}]}


def test_a_shared_expense_crosses_the_seam_both_ways(flat):
    household_id, ana, ben = flat
    created = ana.call("POST", HOUSEHOLDS, f"/households/{household_id}/expenses", expense(ana, ben))
    assert created.status_code == 201, created.text
    ledger = ana.call("GET", PERSONAL, "/transactions").json()
    [row] = [t for t in ledger if t["origin"] == "shared"]
    assert (row["id"], row["amount_cents"]) == (created.json()["payer_transaction_id"], 3000)
    dashboard = ben.call("GET", PERSONAL, "/dashboard").json()
    assert dashboard["households_available"] and dashboard["terms"]["household_payables_cents"] == 1500
    members = ana.call("GET", HOUSEHOLDS, f"/households/{household_id}").json()["members"]
    assert {m["display_name"] for m in members} == {"Ana", "Ben"}  # names from personal


def test_a_confirmed_settlement_writes_both_ledgers(flat):
    household_id, ana, ben = flat
    recorded = ben.call("POST", HOUSEHOLDS, f"/households/{household_id}/settlements",
                        {"payer_user_id": ben.id, "payee_user_id": ana.id, "amount_cents": 1500, "paid_on": TODAY})
    settlement = recorded.json()["settlement"]
    confirmed = ana.call("POST", HOUSEHOLDS, f"/settlements/{settlement['id']}/confirm", {"version": settlement["version"]})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed", confirmed.text
    assert [t["kind"] for t in ana.call("GET", PERSONAL, "/transactions").json() if t["origin"] == "settlement"] == ["income"]
    assert [t["kind"] for t in ben.call("GET", PERSONAL, "/transactions").json() if t["origin"] == "settlement"] == ["expense"]
    assert ben.call("GET", PERSONAL, "/dashboard").json()["terms"]["household_payables_cents"] == 0


def test_with_personal_stopped_households_serves_and_refuses_money_clearly(flat):
    household_id, ana, ben = flat
    compose("stop", "personal")
    try:
        page = ana.call("GET", HOUSEHOLDS, f"/households/{household_id}")
        assert page.status_code == 200  # tokens are checked locally
        assert {m["display_name"] for m in page.json()["members"]} == {f"Member #{ana.id}", f"Member #{ben.id}"}
        started = time.monotonic()
        refused = ana.call("POST", HOUSEHOLDS, f"/households/{household_id}/expenses", expense(ana, ben, 500))
        assert time.monotonic() - started < 5  # the 2 s timeout, not a hung request
        assert refused.status_code == 503 and refused.json()["title"] == "Ledger unavailable"
    finally:
        compose("start", "personal")
        wait_healthy(PERSONAL)
    expenses = ana.call("GET", HOUSEHOLDS, f"/households/{household_id}/expenses").json()
    assert [e["amount_cents"] for e in expenses] == [3000]  # nothing half-saved


def test_with_households_stopped_personal_serves_and_degrades(flat):
    _, ana, _ = flat
    compose("stop", "households")
    try:
        started = time.monotonic()
        dashboard = ana.call("GET", PERSONAL, "/dashboard")
        assert time.monotonic() - started < 8
        assert dashboard.status_code == 200 and dashboard.json()["households_available"] is False
        assert ana.call("POST", PERSONAL, "/transactions", {"kind": "expense", "amount_cents": 250, "occurred_on": TODAY,
                                                           "category_id": 2}).status_code == 201
    finally:
        compose("start", "households")
        wait_healthy(HOUSEHOLDS)
