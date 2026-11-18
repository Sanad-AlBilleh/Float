"""/internal: what the households service needs from this service (Assignment 2 §3, ADR-6).

Only the households service may call these: every request must carry ``X-Internal-Key`` with the shared
INTERNAL_API_KEY secret. They are documented in openapi.yaml with the same shapes the households
service's client expects.

- ``GET /internal/users?ids=1,2``: display names for member lists and settlement notes.
- ``GET /internal/users/{id}/profile``: what a household write needs to check (tracking start, allowance
  day, the user's categories, whether setup is complete).
- ``POST/PATCH/DELETE /internal/transactions``: the payer's ledger row for a shared expense, and the two
  rows of a confirmed settlement. In A1 these were written in the same SQLite transaction as the household
  row; now the households service calls here first and undoes the call if its own write fails (ADR-7).
  ``POST`` takes an ``Idempotency-Key``, so a retried call never records the money twice.
"""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_conn, require_internal
from app.api.v1 import idempotency
from app.api.v1.problems import to_json
from app.api.v1.schemas import Day, Id, body_doc, parse
from app.application.setup import is_setup_complete
from app.db.connection import Connection
from app.db.unit_of_work import transaction
from app.identity import api as identity
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal)])

LINKED = Literal["shared", "settlement"]


class LinkedTransactionIn(BaseModel):
    user_id: Id
    kind: Literal["income", "expense"]
    origin: LINKED
    amount_cents: int = Field(ge=1, le=100_000_000)
    occurred_on: Day
    category_id: Id | None = None
    income_source: Literal["settlement"] | None = None
    note: str = Field(default="", max_length=500)


class LinkedTransactionEdit(BaseModel):
    user_id: Id
    origin: LINKED
    amount_cents: int = Field(ge=1, le=100_000_000)
    occurred_on: Day
    category_id: Id | None = None


class UserName(BaseModel):
    id: int
    display_name: str


class Profile(BaseModel):
    id: int
    display_name: str
    setup_complete: bool
    tracking_start: date | None
    allowance_day: int
    category_ids: list[int]


class Created(BaseModel):
    id: int


def _clock(request: Request):
    return request.app.state.clock


def _check_category(conn: Connection, user_id: int, category_id: int | None) -> None:
    """A shared expense may use a fixed category or one of the payer's own (as in A1)."""
    if category_id is not None and category_id not in {c.id for c in ledger.list_categories(conn, user_id)}:
        raise ValidationError.single("category_id", "Choose one of the listed categories.")


@router.get("/users", response_model=list[UserName])
def users(conn: Connection = Depends(get_conn), ids: str = Query(pattern=r"^\d+(,\d+)*$", max_length=2000)):
    found = []
    for user_id in sorted({int(part) for part in ids.split(",")}):
        try:
            found.append({"id": user_id, "display_name": identity.get_user(conn, user_id).display_name})
        except NotFoundError:
            continue
    return found


@router.get("/users/{user_id}/profile", response_model=Profile, responses={404: {"description": "No such user"}})
def profile(user_id: int, conn: Connection = Depends(get_conn)):
    user = identity.get_user(conn, user_id)
    ledger_settings = ledger.get_settings(conn, user_id)
    planning_settings = planning.get_settings(conn, user_id)
    return {"id": user.id, "display_name": user.display_name, "setup_complete": is_setup_complete(conn, user_id),
            "tracking_start": ledger_settings.tracking_start if ledger_settings else None,
            "allowance_day": planning_settings.allowance_day if planning_settings else 1,
            "category_ids": [c.id for c in ledger.list_categories(conn, user_id)]}


@router.post("/transactions", status_code=201, response_model=Created, openapi_extra=body_doc(LinkedTransactionIn),
             responses={422: {"description": "The ledger refused the transaction"}})
def create_transaction(request: Request, conn: Connection = Depends(get_conn), payload: Any = Body(default=None)):
    data = parse(LinkedTransactionIn, payload)
    clock = _clock(request)

    def produce():
        with transaction(conn):
            if data.kind == "expense" and data.origin == "shared":
                _check_category(conn, data.user_id, data.category_id)
            transaction_id = ledger.create_linked(
                conn, user_id=data.user_id, kind=data.kind, origin=data.origin, amount_cents=data.amount_cents,
                occurred_on=data.occurred_on, category_id=data.category_id, income_source=data.income_source,
                note=data.note, today=clock.today(), now=clock.now_utc())
        return 201, to_json({"id": transaction_id})
    return idempotency.run(conn, request, user_id=data.user_id, payload=payload, clock=clock, produce=produce)


@router.patch("/transactions/{transaction_id}", status_code=204, openapi_extra=body_doc(LinkedTransactionEdit),
              responses={404: {"description": "No such linked transaction"}})
def edit_transaction(transaction_id: int, request: Request, conn: Connection = Depends(get_conn),
                     payload: Any = Body(default=None)):
    data = parse(LinkedTransactionEdit, payload)
    clock = _clock(request)
    with transaction(conn):
        _check_category(conn, data.user_id, data.category_id)
        ledger.update_linked(conn, user_id=data.user_id, transaction_id=transaction_id, origin=data.origin,
                             amount_cents=data.amount_cents, occurred_on=data.occurred_on,
                             category_id=data.category_id, today=clock.today(), now=clock.now_utc())
    return Response(status_code=204)


@router.delete("/transactions/{transaction_id}", status_code=204,
               responses={404: {"description": "No such linked transaction"}})
def delete_transaction(transaction_id: int, user_id: int, origin: LINKED, conn: Connection = Depends(get_conn)):
    with transaction(conn):
        ledger.delete_linked(conn, user_id=user_id, transaction_id=transaction_id, origin=origin)
    return Response(status_code=204)


