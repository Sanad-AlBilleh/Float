"""/api/v1 of the households service: households, members, invitations, shared expenses, balances, settlements,
household bills and the household activity feed (FR-17–26, FR-34). The same routes and bodies as A1; the
other routes live in the personal service (ADR-6). Requests carry ``Authorization: Bearer <token>``."""

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import Session, actor_for, get_conn, require_user
from app.api.v1 import idempotency
from app.api.v1.problems import to_json
from app.api.v1.schemas import (
    CodeIn,
    ExpenseEdit,
    ExpenseIn,
    HouseholdBillIn,
    NameIn,
    OccurrenceEdit,
    PaymentIn,
    ReasonIn,
    RenameIn,
    SeriesIn,
    SettlementIn,
    TransferIn,
    Versioned,
    body_doc,
    parse,
)
from app.application import activity, households, shared_money
from app.application.context import Actor
from app.db.connection import Connection
from app.households.api import SplitEntry, simplify
from app.shared.recurrence import Rule

router = APIRouter(prefix="/api/v1", tags=["v1"])
Payload = Body(default=None)


def ok(value: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(to_json(value), status_code=status)


def _clock(request: Request):
    return request.app.state.clock


def _personal(request: Request):
    return request.app.state.personal


def _rule(data: SeriesIn) -> Rule:
    return Rule(data.freq, data.interval, data.anchor_date, until=data.until, count=data.count)


def _entries(participants) -> tuple[SplitEntry, ...]:
    return tuple(SplitEntry(p.user_id, p.value) for p in participants)


# Households --------------------------------------------------------------------------------------------

def _household(conn, request: Request, actor: Actor, household_id: int, clock) -> dict:
    page = households.page(conn, _personal(request), actor, household_id, clock)
    return to_json({"household": page.household, "me": page.me, "members": page.members,
                    "invitations": page.invitations})


@router.get("/households")
def list_households(request: Request, session: Session = Depends(require_user),
                    conn: Connection = Depends(get_conn)):
    return ok([{**to_json(household), "active_member": active}
               for household, active in households.my_households(conn, actor_for(request, session))])


@router.post("/households", openapi_extra=body_doc(NameIn))
def create_household(request: Request, session: Session = Depends(require_user),
                     conn: Connection = Depends(get_conn), payload: Any = Payload):
    return ok(households.create_household(conn, actor_for(request, session), parse(NameIn, payload).name.strip(),
                                          _clock(request)), 201)


@router.post("/households/join", openapi_extra=body_doc(CodeIn))
def join_household(request: Request, session: Session = Depends(require_user),
                   conn: Connection = Depends(get_conn), payload: Any = Payload):
    return ok(households.join_household(conn, _personal(request), actor_for(request, session), parse(CodeIn, payload).code,
                                        _clock(request)))


@router.get("/households/{household_id}")
def get_household(household_id: int, request: Request, session: Session = Depends(require_user),
                  conn: Connection = Depends(get_conn)):
    return JSONResponse(_household(conn, request, actor_for(request, session), household_id, _clock(request)))


@router.patch("/households/{household_id}", openapi_extra=body_doc(RenameIn))
def rename_household(household_id: int, request: Request, session: Session = Depends(require_user),
                     conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    data = parse(RenameIn, payload)
    households.rename(conn, actor, household_id, data.version, data.name.strip(), _clock(request))
    return JSONResponse(_household(conn, request, actor, household_id, _clock(request)))


@router.post("/households/{household_id}/invitations")
def invite(household_id: int, request: Request, session: Session = Depends(require_user),
           conn: Connection = Depends(get_conn)):
    return ok({"code": households.invite(conn, actor_for(request, session), household_id, _clock(request)),
               "expires_in_hours": 72}, 201)


@router.post("/households/{household_id}/invitations/{invitation_id}/revoke", status_code=204)
def revoke(household_id: int, invitation_id: int, request: Request, session: Session = Depends(require_user),
           conn: Connection = Depends(get_conn)):
    households.revoke(conn, actor_for(request, session), household_id, invitation_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/leave", status_code=204)
def leave(household_id: int, request: Request, session: Session = Depends(require_user),
          conn: Connection = Depends(get_conn)):
    households.leave(conn, actor_for(request, session), household_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/members/{user_id}/remove", status_code=204)
def remove_member(household_id: int, user_id: int, request: Request, session: Session = Depends(require_user),
                  conn: Connection = Depends(get_conn)):
    households.remove(conn, actor_for(request, session), household_id, user_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/transfer", openapi_extra=body_doc(TransferIn))
def transfer(household_id: int, request: Request, session: Session = Depends(require_user),
             conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    data = parse(TransferIn, payload)
    households.transfer(conn, actor, household_id, data.version, data.new_owner_id, _clock(request))
    return JSONResponse(_household(conn, request, actor, household_id, _clock(request)))


@router.post("/households/{household_id}/archive", openapi_extra=body_doc(Versioned))
def archive_household(household_id: int, request: Request, session: Session = Depends(require_user),
                      conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    households.archive(conn, actor, household_id, parse(Versioned, payload).version, _clock(request))
    return JSONResponse(_household(conn, request, actor, household_id, _clock(request)))


# Shared money ------------------------------------------------------------------------------------------

def _expense_draft(data: ExpenseIn) -> shared_money.ExpenseDraft:
    return shared_money.ExpenseDraft(data.amount_cents, data.spent_on, data.category_id, data.description.strip(),
                                     data.one_off, data.split_method, _entries(data.participants))


@router.get("/households/{household_id}/expenses")
def list_expenses(household_id: int, request: Request, session: Session = Depends(require_user),
                  conn: Connection = Depends(get_conn)):
    return ok(households.page(conn, _personal(request), actor_for(request, session), household_id, _clock(request)).expenses)


@router.post("/households/{household_id}/expenses", openapi_extra=body_doc(ExpenseIn))
def create_expense(household_id: int, request: Request, session: Session = Depends(require_user),
                   conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor, clock = actor_for(request, session), _clock(request)
    households.member(conn, actor, household_id)

    def produce():
        draft = _expense_draft(parse(ExpenseIn, payload))
        expense = shared_money.record_expense(conn, _personal(request), actor, household_id, draft, clock)
        return 201, to_json(expense)
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock, produce=produce)


@router.patch("/households/{household_id}/expenses/{expense_id}", openapi_extra=body_doc(ExpenseEdit))
def edit_expense(household_id: int, expense_id: int, request: Request,
                 session: Session = Depends(require_user), conn: Connection = Depends(get_conn),
                 payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_expense(conn, actor, household_id, expense_id)
    data = parse(ExpenseEdit, payload)
    return ok(shared_money.edit_expense(conn, _personal(request), actor, expense_id, data.version, _expense_draft(data),
                                        _clock(request)))


@router.delete("/households/{household_id}/expenses/{expense_id}", status_code=204,
               openapi_extra=body_doc(Versioned))
def delete_expense(household_id: int, expense_id: int, request: Request,
                   session: Session = Depends(require_user), conn: Connection = Depends(get_conn),
                   payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_expense(conn, actor, household_id, expense_id)
    shared_money.delete_expense(conn, _personal(request), actor, expense_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


@router.get("/households/{household_id}/balances")
def balances(household_id: int, request: Request, session: Session = Depends(require_user),
             conn: Connection = Depends(get_conn)):
    households.member(conn, actor_for(request, session), household_id)  # current members only
    page = households.page(conn, _personal(request), actor_for(request, session), household_id, _clock(request))
    nets = {m.user_id: m.net_cents for m in page.members}
    return ok({"nets": [{"user_id": m.user_id, "display_name": m.display_name, "net_cents": m.net_cents}
                        for m in page.members], "plan": simplify(nets)})


@router.get("/households/{household_id}/settlements")
def list_settlements(household_id: int, request: Request, session: Session = Depends(require_user),
                     conn: Connection = Depends(get_conn)):
    return ok(households.page(conn, _personal(request), actor_for(request, session), household_id, _clock(request)).settlements)


@router.post("/households/{household_id}/settlements", openapi_extra=body_doc(SettlementIn))
def record_settlement(household_id: int, request: Request, session: Session = Depends(require_user),
                      conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor, clock = actor_for(request, session), _clock(request)
    households.member(conn, actor, household_id)

    def produce():
        data = parse(SettlementIn, payload)
        settlement, over = shared_money.record_settlement(conn, _personal(request), actor, household_id, data.payer_user_id,
                                                          data.payee_user_id, data.amount_cents, data.paid_on, clock)
        return 201, to_json({"settlement": settlement, "more_than_suggested": over})
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock, produce=produce)


def _settlement_action(name: str):
    def handler(settlement_id: int, request: Request, session: Session = Depends(require_user),
                conn: Connection = Depends(get_conn), payload: Any = Payload):
        actor, clock = actor_for(request, session), _clock(request)
        households.member(conn, actor, shared_money.settlement_household(conn, settlement_id))
        data = parse(ReasonIn, payload)
        if name == "confirm":
            result = shared_money.confirm_settlement(conn, _personal(request), actor, settlement_id, data.version, clock)
        elif name == "reject":
            result = shared_money.reject_settlement(conn, actor, settlement_id, data.version, data.reason.strip(),
                                                    clock)
        else:
            result = shared_money.cancel_settlement(conn, actor, settlement_id, data.version, clock)
        return ok(result)
    handler.__name__ = f"{name}_settlement"
    return handler


for _name in ("confirm", "reject", "cancel"):
    router.add_api_route(f"/settlements/{{settlement_id}}/{_name}", _settlement_action(_name), methods=["POST"],
                         openapi_extra=body_doc(ReasonIn))


@router.get("/households/{household_id}/bills")
def list_household_bills(household_id: int, request: Request, session: Session = Depends(require_user),
                         conn: Connection = Depends(get_conn)):
    return ok(shared_money.household_bills(conn, _personal(request), actor_for(request, session), household_id,
                                              _clock(request)))


@router.post("/households/{household_id}/bills", openapi_extra=body_doc(HouseholdBillIn))
def create_household_bill(household_id: int, request: Request, session: Session = Depends(require_user),
                          conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.owner(conn, actor, household_id)
    data = parse(HouseholdBillIn, payload)
    series = shared_money.add_household_bill(conn, _personal(request), actor, household_id, shared_money.HouseholdBillInput(
        data.name.strip(), data.amount_cents, data.category_id, _rule(data), data.split_method,
        _entries(data.participants)), _clock(request))
    return ok(series, 201)


@router.patch("/household-occurrences/{occurrence_id}", openapi_extra=body_doc(OccurrenceEdit))
def edit_household_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_user),
                              conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_household_occurrence(conn, actor, occurrence_id)
    data = parse(OccurrenceEdit, payload)
    shared_money.edit_household_occurrence(conn, actor, occurrence_id, data.version, data.amount_cents,
                                           data.due_date, _clock(request))
    return ok(shared_money.get_household_occurrence(conn, actor, occurrence_id))


def _household_occurrence_action(name: str):
    def handler(occurrence_id: int, request: Request, session: Session = Depends(require_user),
                conn: Connection = Depends(get_conn), payload: Any = Payload):
        actor, clock = actor_for(request, session), _clock(request)
        shared_money.get_household_occurrence(conn, actor, occurrence_id)
        if name == "pay":
            def produce():
                data = parse(PaymentIn, payload)
                expense = shared_money.pay_household_occurrence(conn, _personal(request), actor, occurrence_id, data.version,
                                                                data.paid_on or clock.today(), clock)
                return 201, to_json(expense)
            return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock,
                                   produce=produce)
        version = parse(Versioned, payload).version
        if name == "undo":
            shared_money.undo_household_payment(conn, _personal(request), actor, occurrence_id, version, clock)
        else:
            shared_money.skip_household_occurrence(conn, actor, occurrence_id, version, clock,
                                                   skipped=name == "skip")
        return ok(shared_money.get_household_occurrence(conn, actor, occurrence_id))
    handler.__name__ = f"{name}_household_occurrence"
    return handler


for _name in ("pay", "undo", "skip", "unskip"):
    router.add_api_route(f"/household-occurrences/{{occurrence_id}}/{_name}", _household_occurrence_action(_name),
                         methods=["POST"], openapi_extra=body_doc(PaymentIn if _name == "pay" else Versioned))


@router.get("/households/{household_id}/activity")
def household_activity(household_id: int, request: Request, session: Session = Depends(require_user),
                       conn: Connection = Depends(get_conn)):
    return ok(activity.household_activity(conn, _personal(request), actor_for(request, session), household_id))
