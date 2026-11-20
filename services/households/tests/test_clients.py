"""The HTTP client for the personal service: errors become the A1 domain errors, silence becomes
PersonalUnavailable, and ledger writes carry an Idempotency-Key (§3, ADR-7)."""

from datetime import date

import httpx2 as httpx
import pytest

from app.clients.personal import PersonalClient, PersonalUnavailable, new_key
from app.shared.errors import ConflictError, NotFoundError, ValidationError


def client(handler) -> PersonalClient:
    return PersonalClient("http://personal:8000", "secret-key", 2.0, transport=httpx.MockTransport(handler))


def create(c: PersonalClient, key: str = "hh-expense-1") -> int:
    return c.create_transaction(user_id=1, kind="expense", origin="shared", amount_cents=3000,
                                occurred_on=date(2026, 9, 19), category_id=1, income_source=None, note="Groceries", key=key)


def test_a_ledger_row_is_created_with_the_key_and_the_internal_key():
    seen = {}

    def handler(request):
        seen.update(key=request.headers["idempotency-key"], internal=request.headers["x-internal-key"],
                    body=request.read())
        return httpx.Response(201, json={"id": 42})
    assert create(client(handler)) == 42
    assert (seen["key"], seen["internal"]) == ("hh-expense-1", "secret-key") and b'"occurred_on":"2026-09-19"' in seen["body"]


@pytest.mark.parametrize("status, body, error", [
    (422, {"title": "Check your input", "errors": {"occurred_on": "Too early."}}, ValidationError),
    (404, {"title": "Not found"}, NotFoundError),
    (409, {"title": "That has changed", "detail": "Not a linked transaction."}, ConflictError),
])
def test_the_ledgers_answers_become_domain_errors(status, body, error):
    with pytest.raises(error) as raised:
        create(client(lambda request: httpx.Response(status, json=body)))
    if error is ValidationError:
        assert raised.value.errors == {"occurred_on": "Too early."}


@pytest.mark.parametrize("handler", [
    lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    lambda request: httpx.Response(500),
    lambda request: httpx.Response(401, json={"title": "Internal endpoint"}),  # a wrong INTERNAL_API_KEY
])
def test_no_usable_answer_means_nothing_was_saved(handler):
    with pytest.raises(PersonalUnavailable, match="nothing was saved"):
        create(client(handler))


def test_names_and_profile():
    def handler(request):
        if request.url.path == "/internal/users":
            assert request.url.params["ids"] == "1,2"
            return httpx.Response(200, json=[{"id": 1, "display_name": "Ana"}])
        return httpx.Response(200, json={"id": 1, "display_name": "Ana", "setup_complete": True,
                                         "tracking_start": "2026-09-01", "allowance_day": 1, "category_ids": [1, 2]})
    c = client(handler)
    assert c.names([2, 1, 1]) == {1: "Ana"} and c.names([]) == {}
    profile = c.profile(1)
    assert profile.tracking_start == date(2026, 9, 1) and profile.category_ids == frozenset({1, 2})


def test_update_and_delete_use_the_linked_row_endpoints():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(204)
    c = client(handler)
    c.update_transaction(5, user_id=1, origin="shared", amount_cents=100, occurred_on=date(2026, 9, 20), category_id=1)
    c.delete_transaction(5, user_id=1, origin="shared")
    assert calls == [("PATCH", "/internal/transactions/5", {}),
                     ("DELETE", "/internal/transactions/5", {"user_id": "1", "origin": "shared"})]


def test_keys_are_unique_and_short_enough():
    first, second = new_key("expense"), new_key("expense")
    assert first != second and len(first) <= 64


def test_a_lost_reply_is_retried_once_with_the_same_key():
    """The ledger saved the row but the reply timed out: the retry with the same key gets the saved row's ID
    back (personal replays it), so a later failure here can still undo it (ADR-7)."""
    keys = []

    def handler(request):
        keys.append(request.headers["idempotency-key"])
        if len(keys) == 1:
            raise httpx.ReadTimeout("reply lost", request=request)
        return httpx.Response(201, json={"id": 42})
    assert create(client(handler)) == 42
    assert keys == ["hh-expense-1", "hh-expense-1"]


def test_a_ledger_that_stays_silent_is_given_up_on_after_one_retry():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused", request=request)
    with pytest.raises(PersonalUnavailable):
        create(client(handler))
    assert len(calls) == 2
