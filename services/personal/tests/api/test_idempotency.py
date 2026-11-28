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


def test_a_concurrent_duplicate_is_refused_while_the_first_runs(client, database_url):
    from app.db.connection import connect

    api = signed_up(client)
    api.post("/transactions", BODY, headers={"Idempotency-Key": "first"})
    conn = connect(database_url, retries=0)
    try:  # as if a second request arrived while the first was still running
        conn.execute("UPDATE idempotency_keys SET status_code = 0 WHERE [key] = 'first'")
    finally:
        conn.close()
    duplicate = api.post("/transactions", BODY, headers={"Idempotency-Key": "first"})
    assert duplicate.status_code == 409 and duplicate.json()["title"] == "Request in progress"
    assert len(api.get("/transactions").json()) == 1


def test_two_requests_racing_for_one_key_get_a_409_not_a_500(client, monkeypatch):
    from contextlib import contextmanager

    from app.api.v1 import idempotency
    from app.db.connection import IntegrityError

    api = signed_up(client)
    real = idempotency.transaction

    @contextmanager
    def raced(conn):  # the other request's reservation commits first and wins the primary key
        with real(conn):
            yield
        raise IntegrityError("Violation of PRIMARY KEY constraint", 2627)

    monkeypatch.setattr(idempotency, "transaction", raced)
    response = api.post("/transactions", BODY, headers={"Idempotency-Key": "double-click"})
    assert response.status_code == 409 and response.json()["title"] == "Request in progress"
    monkeypatch.undo()
    assert api.get("/transactions").json() == []


def test_text_the_database_cannot_store_is_a_422_not_a_500(client):
    api = signed_up(client)
    import json

    for note in ("a\x00b", "a\ud800", "a\x07b"):  # sent as JSON escapes, as a browser would
        response = api.browser.post("/api/v1/transactions", content=json.dumps({**BODY, "note": note}),
                                    headers=api._headers({"Content-Type": "application/json"}))
        assert response.status_code == 422 and "note" in response.json()["errors"]
    assert api.post("/transactions", {**BODY, "note": "line one\nline two\ttabbed"}).status_code == 201
