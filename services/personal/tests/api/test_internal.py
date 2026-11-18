"""/internal: the calls the households service makes across the seam (ADR-6, ADR-7)."""

import pytest

from tests.api.helpers import signed_up

KEY = {"X-Internal-Key": "test-internal-key"}


@pytest.fixture
def ana(client):
    return signed_up(client)


def expense(**changes):
    return {"user_id": 1, "kind": "expense", "origin": "shared", "amount_cents": 3000, "occurred_on": "2026-09-19",
            "category_id": 1, "note": "Groceries", **changes}


def test_profile_has_what_a_household_write_checks(client, ana):
    profile = client.get("/internal/users/1/profile", headers=KEY).json()
    assert profile == {"id": 1, "display_name": "Ana", "setup_complete": True, "tracking_start": "2026-09-01",
                       "allowance_day": 1, "category_ids": list(range(1, 12))}
    assert client.get("/internal/users/99/profile", headers=KEY).status_code == 404


def test_a_shared_expense_lands_in_the_payers_ledger_once_per_key(client, ana):
    headers = {**KEY, "Idempotency-Key": "hh-expense-1"}
    first = client.post("/internal/transactions", json=expense(), headers=headers)
    again = client.post("/internal/transactions", json=expense(), headers=headers)  # a retried call
    assert first.status_code == 201 and again.json() == first.json()
    assert again.headers.get("idempotent-replayed") == "true"
    [row] = ana.get("/transactions").json()
    assert (row["id"], row["origin"], row["amount_cents"]) == (first.json()["id"], "shared", 3000)


def test_linked_rows_can_be_changed_and_removed_only_as_linked_rows(client, ana):
    created = client.post("/internal/transactions", json=expense(), headers=KEY).json()["id"]
    edit = {"user_id": 1, "origin": "shared", "amount_cents": 4500, "occurred_on": "2026-09-19", "category_id": 2}
    assert client.patch(f"/internal/transactions/{created}", json=edit, headers=KEY).status_code == 204
    assert ana.get(f"/transactions/{created}").json()["amount_cents"] == 4500
    wrong = client.delete(f"/internal/transactions/{created}", params={"user_id": 1, "origin": "settlement"},
                          headers=KEY)
    assert wrong.status_code == 409  # a shared expense is not a settlement row
    gone = client.delete(f"/internal/transactions/{created}", params={"user_id": 1, "origin": "shared"}, headers=KEY)
    assert gone.status_code == 204 and ana.get("/transactions").json() == []


def test_the_ledger_rules_still_apply(client, ana):
    before_tracking = client.post("/internal/transactions", json=expense(occurred_on="2026-08-01"), headers=KEY)
    assert before_tracking.status_code == 422 and "occurred_on" in before_tracking.json()["errors"]
    someone_elses = client.post("/internal/transactions", json=expense(category_id=999), headers=KEY)
    assert someone_elses.status_code == 422 and "category_id" in someone_elses.json()["errors"]


def test_settlements_record_an_expense_and_an_income(client, ana, make_client):
    signed_up(make_client(), "ben")
    out = {"user_id": 1, "kind": "expense", "origin": "settlement", "amount_cents": 1000, "occurred_on": "2026-09-20",
           "note": "Settlement to Ben"}
    back = {"user_id": 2, "kind": "income", "origin": "settlement", "income_source": "settlement",
            "amount_cents": 1000, "occurred_on": "2026-09-20", "note": "Settlement from Ana"}
    assert client.post("/internal/transactions", json=out, headers=KEY).status_code == 201
    assert client.post("/internal/transactions", json=back, headers=KEY).status_code == 201
