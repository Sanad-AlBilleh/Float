"""The HTTP client for the households service: timeouts and errors become HouseholdsUnavailable (§3)."""

from datetime import date

import httpx2 as httpx
import pytest

from app.clients.households import HouseholdsClient, HouseholdsUnavailable


def client(handler) -> HouseholdsClient:
    return HouseholdsClient("http://households:8000", "secret-key", 2.0, transport=httpx.MockTransport(handler))


def test_position_is_parsed_and_the_internal_key_is_sent():
    seen = {}

    def handler(request):
        seen["key"] = request.headers["x-internal-key"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"in_household": True, "bill_shares_cents": 1200, "payables_cents": 1000,
                                         "receivables_cents": 0,
                                         "commitments": [{"due_date": "2026-09-28", "amount_cents": 1200}],
                                         "open_bills": [{"occurrence_id": 1, "household_id": 2, "name": "Internet",
                                                         "due_date": "2026-09-28", "share_cents": 1200}]})
    position = client(handler).position(7, window_end=date(2026, 10, 1), horizon_end=date(2026, 11, 1))
    assert seen["key"] == "secret-key" and "/internal/users/7/position" in seen["url"]
    assert position.commitments == ((date(2026, 9, 28), 1200),) and position.open_bills[0].name == "Internet"
    assert position.available


@pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_no_answer_is_unavailable(failure):
    def handler(request):
        raise failure
    with pytest.raises(HouseholdsUnavailable):
        client(handler).shares(7, start=date(2026, 9, 1), end_exclusive=date(2026, 10, 1))


def test_a_server_error_is_unavailable():
    with pytest.raises(HouseholdsUnavailable):
        client(lambda request: httpx.Response(503, json={"title": "Starting up"})).events(7, after=0)


@pytest.mark.parametrize("status", [401, 404, 422])
def test_a_refused_read_is_unavailable_too(status):
    """A wrong INTERNAL_API_KEY on one side must degrade the dashboard, not turn it into a 500."""
    with pytest.raises(HouseholdsUnavailable):
        client(lambda request: httpx.Response(status, json={"title": "No"})).events(7, after=0)


def test_events_are_parsed():
    body = {"last_id": 9, "expenses": [{"audit_event_id": 9, "household_id": 1, "actor_user_id": 3,
                                        "description": "Pizza", "share_cents": 1500}],
            "settlements": [{"settlement_id": 4, "household_id": 1, "other_user_id": 3, "amount_cents": 1000,
                             "verb": "paid you"}]}
    events = client(lambda request: httpx.Response(200, json=body)).events(7, after=0)
    assert events.last_id == 9 and events.expenses[0].share_cents == 1500 and events.settlements[0].verb == "paid you"


def test_the_real_client_has_a_timeout():
    real = HouseholdsClient("http://households:8000", "k", 1.5)
    assert real._client.timeout.read == 1.5
