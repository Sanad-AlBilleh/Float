"""/internal: what the personal service needs from this service (Assignment 2 §3, ADR-6).

Only the personal service may call these (``X-Internal-Key`` with INTERNAL_API_KEY). The shapes match the
personal service's client (app/clients/households.py there) and both openapi.yaml files.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_conn, require_internal
from app.api.v1.problems import to_json
from app.application import summary
from app.db.connection import Connection

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal)])


class Commitment(BaseModel):
    due_date: date
    amount_cents: int


class OpenBill(BaseModel):
    occurrence_id: int
    household_id: int
    name: str
    due_date: date
    share_cents: int


class Position(BaseModel):
    in_household: bool
    bill_shares_cents: int
    payables_cents: int
    receivables_cents: int
    commitments: list[Commitment]
    open_bills: list[OpenBill]


class Share(BaseModel):
    amount_cents: int
    occurred_on: date
    category_id: int
    from_household_bill: bool
    one_off: bool


class ExpenseEvent(BaseModel):
    audit_event_id: int
    household_id: int
    actor_user_id: int
    description: str
    share_cents: int


class AwaitingSettlement(BaseModel):
    settlement_id: int
    household_id: int
    other_user_id: int
    amount_cents: int
    verb: str


class Events(BaseModel):
    last_id: int
    expenses: list[ExpenseEvent]
    settlements: list[AwaitingSettlement]


@router.get("/users/{user_id}/position", response_model=Position)
def position(user_id: int, window_end: date, horizon_end: date, conn: Connection = Depends(get_conn)):
    """The user's household terms for safe-to-spend, and their open bill shares for alerts."""
    return to_json(summary.position(conn, user_id=user_id, window_end=window_end, horizon_end=horizon_end))


@router.get("/users/{user_id}/shares", response_model=list[Share])
def shares(user_id: int, start: date, end: date, conn: Connection = Depends(get_conn)):
    """The user's shares of shared expenses dated in [start, end), for the forecast and budgets."""
    return to_json(summary.shares(conn, user_id=user_id, start=start, end_exclusive=end))


@router.get("/users/{user_id}/events", response_model=Events)
def events(user_id: int, after: int = Query(default=0, ge=0), conn: Connection = Depends(get_conn)):
    """Events for the user's alerts since ``after`` (the personal service's stored cursor)."""
    return summary.events(conn, user_id=user_id, after=after)
