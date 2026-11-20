"""The personal service's view of the households service, over HTTP (Assignment 2, ADR-6).

In A1 the dashboard and the alerts read the Households tables directly. Those tables are now in the
other service's database, so these three calls replace those reads:

- ``position``: the user's household terms for safe-to-spend (bill shares, what they owe and are owed).
- ``shares``: the user's shares of shared expenses, for the spending forecast.
- ``events``: shared expenses by other members and settlements waiting for the user, for alerts.

Every call has a timeout (HOUSEHOLDS_TIMEOUT_S, default 2 s). A timeout, a refused connection or a 5xx
answer raises ``HouseholdsUnavailable``; callers decide how to degrade (ADR-6, D5 in plan.md).
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx2 as httpx

logger = logging.getLogger(__name__)


class HouseholdsUnavailable(Exception):
    """The households service did not answer in time, or answered with an error."""


@dataclass(frozen=True)
class OpenBill:
    occurrence_id: int
    household_id: int
    name: str
    due_date: date
    share_cents: int


@dataclass(frozen=True)
class Position:
    in_household: bool
    bill_shares_cents: int
    payables_cents: int
    receivables_cents: int
    commitments: tuple[tuple[date, int], ...]
    open_bills: tuple[OpenBill, ...]
    available: bool = True


NO_POSITION = Position(False, 0, 0, 0, (), (), available=False)  # the service did not answer
EMPTY_POSITION = Position(False, 0, 0, 0, (), ())  # no households service configured (unit tests)


@dataclass(frozen=True)
class Share:
    amount_cents: int
    occurred_on: date
    category_id: int
    from_household_bill: bool
    one_off: bool


@dataclass(frozen=True)
class ExpenseEvent:
    audit_event_id: int
    household_id: int
    actor_user_id: int
    description: str
    share_cents: int


@dataclass(frozen=True)
class AwaitingSettlement:
    settlement_id: int
    household_id: int
    other_user_id: int
    amount_cents: int
    verb: str


@dataclass(frozen=True)
class Events:
    last_id: int
    expenses: tuple[ExpenseEvent, ...]
    settlements: tuple[AwaitingSettlement, ...]


class HouseholdsClient:
    def __init__(self, base_url: str, internal_key: str, timeout_s: float,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport,
                                    headers={"X-Internal-Key": internal_key})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as error:  # timeouts and refused connections
            raise HouseholdsUnavailable("Household data is unavailable right now.") from error
        if not response.is_success:
            # 5xx: households is failing. 401/404/422: these are fixed reads, so it means a configuration
            # problem (for example a different INTERNAL_API_KEY); the pages still degrade the designed way.
            if response.status_code < 500:
                logger.warning("households answered %s for %s", response.status_code, path)
            raise HouseholdsUnavailable("Household data is unavailable right now.")
        return response.json()

    def position(self, user_id: int, *, window_end: date, horizon_end: date) -> Position:
        data = self._get(f"/internal/users/{user_id}/position",
                         {"window_end": window_end.isoformat(), "horizon_end": horizon_end.isoformat()})
        return Position(
            in_household=data["in_household"],
            bill_shares_cents=data["bill_shares_cents"],
            payables_cents=data["payables_cents"],
            receivables_cents=data["receivables_cents"],
            commitments=tuple((date.fromisoformat(c["due_date"]), c["amount_cents"]) for c in data["commitments"]),
            open_bills=tuple(OpenBill(b["occurrence_id"], b["household_id"], b["name"],
                                      date.fromisoformat(b["due_date"]), b["share_cents"])
                             for b in data["open_bills"]),
        )

    def shares(self, user_id: int, *, start: date, end_exclusive: date) -> list[Share]:
        rows = self._get(f"/internal/users/{user_id}/shares",
                         {"start": start.isoformat(), "end": end_exclusive.isoformat()})
        return [Share(r["amount_cents"], date.fromisoformat(r["occurred_on"]), r["category_id"],
                      r["from_household_bill"], r["one_off"]) for r in rows]

    def events(self, user_id: int, *, after: int) -> Events:
        data = self._get(f"/internal/users/{user_id}/events", {"after": after})
        return Events(
            last_id=data["last_id"],
            expenses=tuple(ExpenseEvent(e["audit_event_id"], e["household_id"], e["actor_user_id"],
                                        e["description"], e["share_cents"]) for e in data["expenses"]),
            settlements=tuple(AwaitingSettlement(s["settlement_id"], s["household_id"], s["other_user_id"],
                                                 s["amount_cents"], s["verb"]) for s in data["settlements"]),
        )
