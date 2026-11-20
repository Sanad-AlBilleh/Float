"""The households service's view of the personal service, over HTTP (Assignment 2, ADR-6 and ADR-7).

Users, their settings, their categories and their ledgers live in the personal service. A household
write that moves money (a shared expense, a bill payment, a confirmed settlement) records the ledger
rows there through ``/internal/transactions``; this client is the only code that makes those calls.

Every call has a timeout (PERSONAL_TIMEOUT_S, default 2 s) and sends the shared INTERNAL_API_KEY.
A timeout, a refused connection or a 5xx answer raises ``PersonalUnavailable``, which the API turns into
503 "your ledger is unavailable, nothing was saved". The personal service's own answers are turned
back into the domain errors the A1 code already handles: 422 -> ValidationError, 404 -> NotFoundError,
409 -> ConflictError.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx2 as httpx

from app.shared.errors import ConflictError, NotFoundError, ValidationError


class PersonalUnavailable(Exception):
    """The personal service did not answer in time, or answered with an error."""

    def __init__(self, message: str = "Your ledger is unavailable right now, so nothing was saved. "
                                      "Try again in a minute.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class Profile:
    id: int
    display_name: str
    setup_complete: bool
    tracking_start: date | None
    allowance_day: int
    category_ids: frozenset[int]


def new_key(purpose: str) -> str:
    """An Idempotency-Key for one ledger write; a retry with the same key never records money twice."""
    return f"hh-{purpose}-{uuid.uuid4().hex}"


class PersonalClient:
    def __init__(self, base_url: str, internal_key: str, timeout_s: float,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport,
                                    headers={"X-Internal-Key": internal_key})

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:  # timeouts and refused connections
            raise PersonalUnavailable() from error
        if response.status_code >= 500 or response.status_code == 401:
            raise PersonalUnavailable()
        if response.status_code == 404:
            raise NotFoundError("No such record in the ledger.")
        if response.status_code in (409, 422):
            body = response.json() if response.content else {}
            if response.status_code == 409:
                raise ConflictError(body.get("detail") or "That has changed.")
            raise ValidationError(body.get("errors") or {"body": body.get("detail") or "Not valid."})
        response.raise_for_status()
        return response

    def names(self, user_ids) -> dict[int, str]:
        ids = sorted(set(user_ids))
        if not ids:
            return {}
        rows = self._request("GET", "/internal/users", params={"ids": ",".join(map(str, ids))}).json()
        return {row["id"]: row["display_name"] for row in rows}

    def profile(self, user_id: int) -> Profile:
        data = self._request("GET", f"/internal/users/{user_id}/profile").json()
        start = data["tracking_start"]
        return Profile(data["id"], data["display_name"], data["setup_complete"],
                       date.fromisoformat(start) if start else None, data["allowance_day"],
                       frozenset(data["category_ids"]))

    def create_transaction(self, *, user_id: int, kind: str, origin: str, amount_cents: int, occurred_on: date,
                           category_id: int | None, income_source: str | None, note: str, key: str) -> int:
        body = {"user_id": user_id, "kind": kind, "origin": origin, "amount_cents": amount_cents,
                "occurred_on": occurred_on.isoformat(), "category_id": category_id,
                "income_source": income_source, "note": note[:500]}
        try:
            response = self._request("POST", "/internal/transactions", json=body, headers={"Idempotency-Key": key})
        except PersonalUnavailable:
            # The row may have been saved and only the reply lost (a timeout). One retry with the same key
            # returns the saved row instead of a second one, so the caller learns its ID and can undo it.
            response = self._request("POST", "/internal/transactions", json=body, headers={"Idempotency-Key": key})
        return response.json()["id"]

    def update_transaction(self, transaction_id: int, *, user_id: int, origin: str, amount_cents: int,
                           occurred_on: date, category_id: int | None) -> None:
        body = {"user_id": user_id, "origin": origin, "amount_cents": amount_cents,
                "occurred_on": occurred_on.isoformat(), "category_id": category_id}
        self._request("PATCH", f"/internal/transactions/{transaction_id}", json=body)

    def delete_transaction(self, transaction_id: int, *, user_id: int, origin: str) -> None:
        self._request("DELETE", f"/internal/transactions/{transaction_id}",
                      params={"user_id": user_id, "origin": origin})
