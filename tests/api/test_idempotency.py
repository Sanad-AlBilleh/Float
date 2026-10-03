"""Idempotency keys on money-creating API posts (FR-35, AT-26)."""

from tests.api.helpers import signed_up

BODY = {"kind": "expense", "amount_cents": 990, "occurred_on": "2026-09-20", "category_id": 2}


def test_a_replay_returns_the_same_response_and_creates_nothing(client):
    api = signed_up(client)
    first = api.post("/transactions", BODY, headers={"Idempotency-Key": "lunch-1"})
    second = api.post("/transactions", BODY, headers={"Idempotency-Key": "lunch-1"})
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["idempotent-replayed"] == "true"
    assert len(api.get("/transactions").json()) == 1


def test_the_same_key_with_a_different_body_is_a_conflict(client):
    api = signed_up(client)
    api.post("/transactions", BODY, headers={"Idempotency-Key": "lunch-1"})
    other = api.post("/transactions", {**BODY, "amount_cents": 991}, headers={"Idempotency-Key": "lunch-1"})
    assert other.status_code == 409
    assert len(api.get("/transactions").json()) == 1


def test_keys_belong_to_one_user_and_expire_after_a_day(client, make_client, clock):
    ana = signed_up(client)
    ben = signed_up(make_client(), "ben")
    ana.post("/transactions", BODY, headers={"Idempotency-Key": "k"})
    assert ben.post("/transactions", BODY, headers={"Idempotency-Key": "k"}).status_code == 201
    clock.advance(hours=24, seconds=1)
    assert ana.post("/transactions", BODY, headers={"Idempotency-Key": "k"}).status_code == 201
    assert len(ana.get("/transactions").json()) == 2


def test_a_failed_request_does_not_burn_the_key(client):
    api = signed_up(client)
    bad = api.post("/transactions", {**BODY, "amount_cents": 0}, headers={"Idempotency-Key": "retry"})
    assert bad.status_code == 422
    assert api.post("/transactions", BODY, headers={"Idempotency-Key": "retry"}).status_code == 201


def test_malformed_keys_are_rejected(client):
    api = signed_up(client)
    for key in ("", "x" * 65, "has space"):
        assert api.post("/transactions", BODY, headers={"Idempotency-Key": key}).status_code == 400


def test_a_concurrent_duplicate_is_refused_while_the_first_runs(client, settings):
    from app.db.connection import connect

    api = signed_up(client)
    api.post("/transactions", BODY, headers={"Idempotency-Key": "first"})
    conn = connect(settings.db_path)
    try:  # as if a second request arrived while the first was still running
        conn.execute("UPDATE idempotency_keys SET status_code = 0 WHERE key = 'first'")
    finally:
        conn.close()
    duplicate = api.post("/transactions", BODY, headers={"Idempotency-Key": "first"})
    assert duplicate.status_code == 409 and duplicate.json()["title"] == "Request in progress"
    assert len(api.get("/transactions").json()) == 1
