"""/api/v1: the same use cases as the HTML pages, with the same services, authorization, and validation
(FR-34, SRS §8.2). Unsafe methods need the X-CSRF-Token header; errors are problem+json."""

import sqlite3
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1 import idempotency
from app.api.v1.problems import problem, to_json
from app.api.v1.schemas import (
    CodeIn,
    Credentials,
    ExpenseEdit,
    ExpenseIn,
    GoalEdit,
    GoalIn,
    HouseholdBillIn,
    LimitIn,
    MovementIn,
    NameIn,
    OccurrenceEdit,
    PasswordChange,
    PaymentIn,
    PlannedAllowanceIn,
    ReasonIn,
    Registration,
    RenameIn,
    SeriesIn,
    SettlementIn,
    SetupIn,
    SplitIn,
    TransactionEdit,
    TransactionIn,
    TransferIn,
    Versioned,
    body_doc,
    parse,
)
from app.application import (
    accounts,
    activity,
    alerts,
    bills,
    budgets,
    goals,
    households,
    setup,
    shared_money,
    transactions,
)
from app.application.context import Actor
from app.application.dashboard import dashboard, forecast
from app.households.api import SplitEntry, simplify
from app.identity.api import Session, new_token
from app.insights.api import preview
from app.ledger.api import TransactionDraft
from app.shared.errors import ValidationError
from app.shared.money import parse_money
from app.shared.recurrence import Rule
from app.web.deps import actor_for, current_session, get_conn, require_ready_session, require_session, verify_csrf
from app.web.rendering import set_cookie
from app.web.security import ANON_CSRF_COOKIE, SESSION_COOKIE

router = APIRouter(prefix="/api/v1", tags=["v1"], dependencies=[Depends(verify_csrf)])
Payload = Body(default=None)


def ok(value: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(to_json(value), status_code=status)


def _clock(request: Request):
    return request.app.state.clock


def _max_age(request: Request) -> timedelta:
    return timedelta(days=request.app.state.settings.session_max_days)


def _signed_in(request: Request, session: Session, token: str, status: int) -> JSONResponse:
    response = ok({"user": {"id": session.user.id, "username": session.user.username,
                            "display_name": session.user.display_name}, "csrf_token": session.csrf_token}, status)
    set_cookie(response, request, SESSION_COOKIE, token, max_age=int(_max_age(request).total_seconds()))
    return response


def _rule(data: SeriesIn) -> Rule:
    return Rule(data.freq, data.interval, data.anchor_date, until=data.until, count=data.count)


def _entries(participants) -> tuple[SplitEntry, ...]:
    return tuple(SplitEntry(p.user_id, p.value) for p in participants)


# Auth --------------------------------------------------------------------------------------------------

@router.get("/csrf")
def csrf(request: Request, session: Session | None = Depends(current_session)):
    """The token to send as X-CSRF-Token: the session's, or a new anonymous double-submit token."""
    if session is not None:
        return ok({"csrf_token": session.csrf_token})
    token = request.cookies.get(ANON_CSRF_COOKIE) or new_token()
    response = ok({"csrf_token": token})
    set_cookie(response, request, ANON_CSRF_COOKIE, token, max_age=None)
    return response


@router.post("/auth/register", openapi_extra=body_doc(Registration))
def register(request: Request, conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(Registration, payload)
    session, token = accounts.register_account(conn, username=data.username, display_name=data.display_name,
                                               password=data.password, clock=_clock(request),
                                               max_age=_max_age(request))
    return _signed_in(request, session, token, 201)


@router.post("/auth/login", openapi_extra=body_doc(Credentials))
def login(request: Request, conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(Credentials, payload)
    session, token = accounts.log_in(conn, username=data.username, password=data.password,
                                     client_address=request.client.host if request.client else "unknown",
                                     clock=_clock(request), max_age=_max_age(request))
    return _signed_in(request, session, token, 200)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn),
           session: Session = Depends(require_session)):
    accounts.log_out(conn, token=request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(session: Session = Depends(require_session), conn: sqlite3.Connection = Depends(get_conn)):
    return ok({"id": session.user.id, "username": session.user.username, "display_name": session.user.display_name,
               "setup_complete": setup.is_setup_complete(conn, session.user.id), "csrf_token": session.csrf_token})


@router.post("/me/password", status_code=204, openapi_extra=body_doc(PasswordChange))
def change_password(request: Request, session: Session = Depends(require_session),
                    conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(PasswordChange, payload)
    accounts.change_password(conn, session=session, current_password=data.current_password,
                             new_password=data.new_password, clock=_clock(request))
    return Response(status_code=204)


# Setup and settings ------------------------------------------------------------------------------------

@router.post("/setup", openapi_extra=body_doc(SetupIn))
def complete_setup(request: Request, session: Session = Depends(require_session),
                   conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(SetupIn, payload)
    setup.complete_setup(conn, actor_for(request, session),
                         setup.SetupInput(data.tracking_start, data.opening_balance_cents, data.allowance_day,
                                          data.planned_allowance_cents, data.allowance_included,
                                          data.monthly_savings_cents), _clock(request))
    return settings(session, conn)


@router.get("/settings")
def settings(session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn)):
    ledger_settings, planning_settings = setup.current_settings(conn, session.user.id)
    return ok({"ledger": ledger_settings, "planning": planning_settings})


@router.patch("/settings", openapi_extra=body_doc(PlannedAllowanceIn))
def update_settings(request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(PlannedAllowanceIn, payload)
    setup.update_planned_allowance(conn, actor_for(request, session), data.planned_allowance_cents, _clock(request))
    return settings(session, conn)


# Transactions ------------------------------------------------------------------------------------------

def _draft(conn: sqlite3.Connection, actor: Actor, data: TransactionIn) -> TransactionDraft:
    """An expense without a category gets the one its note suggests, exactly as on the form."""
    category_id = data.category_id
    if data.kind == "expense" and category_id is None:
        category_id = transactions.suggested_category(conn, actor, data.note)
        if category_id is None:
            raise ValidationError.single("note", transactions.NOTE_FOR_CATEGORY)
    return TransactionDraft(data.kind, data.amount_cents, data.occurred_on, category_id, data.income_source,
                            data.one_off, data.note.strip())


@router.get("/transactions")
def list_transactions(request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn), limit: int = 50):
    return ok(transactions.list_transactions(conn, actor_for(request, session), limit=max(1, min(limit, 200))))


@router.post("/transactions", openapi_extra=body_doc(TransactionIn))
def create_transaction(request: Request, session: Session = Depends(require_ready_session),
                       conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)

    def produce():
        data = parse(TransactionIn, payload)
        return 201, to_json(transactions.add_transaction(conn, actor, _draft(conn, actor, data), _clock(request)))
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=_clock(request),
                           produce=produce)


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return ok(transactions.get_transaction(conn, actor_for(request, session), transaction_id))


@router.patch("/transactions/{transaction_id}", openapi_extra=body_doc(TransactionEdit))
def edit_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    transactions.get_transaction(conn, actor, transaction_id)
    data = parse(TransactionEdit, payload)
    return ok(transactions.edit_transaction(conn, actor, transaction_id, data.version, _draft(conn, actor, data),
                                           _clock(request)))


@router.delete("/transactions/{transaction_id}", status_code=204, openapi_extra=body_doc(Versioned))
def delete_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                       conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    transactions.get_transaction(conn, actor, transaction_id)
    transactions.remove_transaction(conn, actor, transaction_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


# Bills --------------------------------------------------------------------------------------------------

@router.get("/bills")
def list_bills(request: Request, session: Session = Depends(require_ready_session),
               conn: sqlite3.Connection = Depends(get_conn)):
    return ok(bills.overview(conn, actor_for(request, session), _clock(request)).series)


@router.post("/bills", openapi_extra=body_doc(SeriesIn))
def create_bill(request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(SeriesIn, payload)
    series = bills.add_series(conn, actor_for(request, session),
                              bills.SeriesInput(data.name.strip(), data.amount_cents, data.category_id, _rule(data)),
                              _clock(request))
    return ok(series, 201)


@router.post("/bills/{series_id}/end", openapi_extra=body_doc(Versioned))
def end_bill(series_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    bills.get_series(conn, actor, series_id)
    bills.end_series(conn, actor, series_id, parse(Versioned, payload).version, _clock(request))
    return ok(bills.get_series(conn, actor, series_id))


@router.get("/occurrences")
def list_occurrences(request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn), start: date | None = None,
                     end: date | None = None):
    view = bills.overview(conn, actor_for(request, session), _clock(request))
    return ok(view.in_range(start, end))


@router.patch("/occurrences/{occurrence_id}", openapi_extra=body_doc(OccurrenceEdit))
def edit_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    bills.get_occurrence(conn, actor, occurrence_id)
    data = parse(OccurrenceEdit, payload)
    bills.edit_occurrence(conn, actor, occurrence_id, data.version, data.amount_cents, data.due_date, _clock(request))
    return ok(bills.get_occurrence(conn, actor, occurrence_id))


@router.post("/occurrences/{occurrence_id}/pay", openapi_extra=body_doc(PaymentIn))
def pay_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                   conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor, clock = actor_for(request, session), _clock(request)
    bills.get_occurrence(conn, actor, occurrence_id)

    def produce():
        data = parse(PaymentIn, payload)
        transaction_id = bills.pay_occurrence(conn, actor, occurrence_id, data.version, data.paid_on or clock.today(),
                                              clock)
        return 201, to_json({"transaction_id": transaction_id,
                             "occurrence": bills.get_occurrence(conn, actor, occurrence_id)})
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock, produce=produce)


def _occurrence_action(name: str, action):
    def handler(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
        actor = actor_for(request, session)
        bills.get_occurrence(conn, actor, occurrence_id)
        action(conn, actor, occurrence_id, parse(Versioned, payload).version, _clock(request))
        return ok(bills.get_occurrence(conn, actor, occurrence_id))
    handler.__name__ = f"{name}_occurrence"
    return handler


for _name, _action in (("undo", bills.undo_payment), ("skip", bills.skip_occurrence),
                       ("unskip", bills.unskip_occurrence)):
    router.add_api_route(f"/occurrences/{{occurrence_id}}/{_name}", _occurrence_action(_name, _action),
                         methods=["POST"], openapi_extra=body_doc(Versioned))


@router.post("/occurrences/{occurrence_id}/split", openapi_extra=body_doc(SplitIn))
def split_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    bills.get_occurrence(conn, actor, occurrence_id)
    data = parse(SplitIn, payload)
    series = bills.split_series(conn, actor, occurrence_id, data.version,
                                bills.SeriesInput(data.name.strip(), data.amount_cents, data.category_id,
                                                  _rule(data)), _clock(request))
    return ok(series, 201)


# Goals and budgets -------------------------------------------------------------------------------------

def _goal_input(data: GoalIn) -> goals.GoalInput:
    return goals.GoalInput(data.name.strip(), data.target_cents, data.target_date, data.priority, data.auto_reserve)


@router.get("/goals")
def list_goals(request: Request, session: Session = Depends(require_ready_session),
               conn: sqlite3.Connection = Depends(get_conn)):
    return ok([{**to_json(goal), "plan": to_json(plan)}
               for goal, plan in goals.goal_plans(conn, actor_for(request, session), _clock(request))])


@router.post("/goals", openapi_extra=body_doc(GoalIn))
def create_goal(request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    return ok(goals.add_goal(conn, actor_for(request, session), _goal_input(parse(GoalIn, payload)), _clock(request)),
              201)


@router.patch("/goals/{goal_id}", openapi_extra=body_doc(GoalEdit))
def edit_goal(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
              conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    data = parse(GoalEdit, payload)
    return ok(goals.edit_goal(conn, actor, goal_id, data.version, _goal_input(data), _clock(request)))


@router.post("/goals/{goal_id}/movements", openapi_extra=body_doc(MovementIn))
def move_goal_money(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    return ok(goals.move_money(conn, actor, goal_id, parse(MovementIn, payload).delta_cents, _clock(request)), 201)


@router.post("/goals/{goal_id}/archive", status_code=204, openapi_extra=body_doc(Versioned))
def archive_goal(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
                 conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    goals.archive_goal(conn, actor, goal_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


def _budget_rows(conn, actor, clock):
    _, rows = budgets.budgets(conn, actor, clock)
    return [{"category_id": row.category.id, "category": row.category.name, "consumption_cents": row.consumption_cents,
             "limit_cents": row.limit_cents, "template_cents": row.limits.template_cents,
             "override_cents": row.limits.override_cents, "state": row.state} for row in rows]


@router.get("/budgets")
def list_budgets(request: Request, session: Session = Depends(require_ready_session),
                 conn: sqlite3.Connection = Depends(get_conn)):
    return ok(_budget_rows(conn, actor_for(request, session), _clock(request)))


@router.put("/budgets/{category_id}", openapi_extra=body_doc(LimitIn))
def set_budget(category_id: int, request: Request, session: Session = Depends(require_ready_session),
               conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    data = parse(LimitIn, payload)
    budgets.set_limit(conn, actor, category_id, data.limit_cents, data.scope, _clock(request))
    return ok(next(row for row in _budget_rows(conn, actor, _clock(request)) if row["category_id"] == category_id))


# Households --------------------------------------------------------------------------------------------

def _household(conn, actor: Actor, household_id: int, clock) -> dict:
    page = households.page(conn, actor, household_id, clock)
    return to_json({"household": page.household, "me": page.me, "members": page.members,
                    "invitations": page.invitations})


@router.get("/households")
def list_households(request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return ok([{**to_json(household), "active_member": active}
               for household, active in households.my_households(conn, actor_for(request, session))])


@router.post("/households", openapi_extra=body_doc(NameIn))
def create_household(request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    return ok(households.create_household(conn, actor_for(request, session), parse(NameIn, payload).name.strip(),
                                          _clock(request)), 201)


@router.post("/households/join", openapi_extra=body_doc(CodeIn))
def join_household(request: Request, session: Session = Depends(require_ready_session),
                   conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    return ok(households.join_household(conn, actor_for(request, session), parse(CodeIn, payload).code,
                                        _clock(request)))


@router.get("/households/{household_id}")
def get_household(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    return JSONResponse(_household(conn, actor_for(request, session), household_id, _clock(request)))


@router.patch("/households/{household_id}", openapi_extra=body_doc(RenameIn))
def rename_household(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    data = parse(RenameIn, payload)
    households.rename(conn, actor, household_id, data.version, data.name.strip(), _clock(request))
    return JSONResponse(_household(conn, actor, household_id, _clock(request)))


@router.post("/households/{household_id}/invitations")
def invite(household_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn)):
    return ok({"code": households.invite(conn, actor_for(request, session), household_id, _clock(request)),
               "expires_in_hours": 72}, 201)


@router.post("/households/{household_id}/invitations/{invitation_id}/revoke", status_code=204)
def revoke(household_id: int, invitation_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn)):
    households.revoke(conn, actor_for(request, session), household_id, invitation_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/leave", status_code=204)
def leave(household_id: int, request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn)):
    households.leave(conn, actor_for(request, session), household_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/members/{user_id}/remove", status_code=204)
def remove_member(household_id: int, user_id: int, request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    households.remove(conn, actor_for(request, session), household_id, user_id, _clock(request))
    return Response(status_code=204)


@router.post("/households/{household_id}/transfer", openapi_extra=body_doc(TransferIn))
def transfer(household_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    data = parse(TransferIn, payload)
    households.transfer(conn, actor, household_id, data.version, data.new_owner_id, _clock(request))
    return JSONResponse(_household(conn, actor, household_id, _clock(request)))


@router.post("/households/{household_id}/archive", openapi_extra=body_doc(Versioned))
def archive_household(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.viewer(conn, actor, household_id)
    households.archive(conn, actor, household_id, parse(Versioned, payload).version, _clock(request))
    return JSONResponse(_household(conn, actor, household_id, _clock(request)))


# Shared money ------------------------------------------------------------------------------------------

def _expense_draft(data: ExpenseIn) -> shared_money.ExpenseDraft:
    return shared_money.ExpenseDraft(data.amount_cents, data.spent_on, data.category_id, data.description.strip(),
                                     data.one_off, data.split_method, _entries(data.participants))


@router.get("/households/{household_id}/expenses")
def list_expenses(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    return ok(households.page(conn, actor_for(request, session), household_id, _clock(request)).expenses)


@router.post("/households/{household_id}/expenses", openapi_extra=body_doc(ExpenseIn))
def create_expense(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                   conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor, clock = actor_for(request, session), _clock(request)
    households.member(conn, actor, household_id)

    def produce():
        expense = shared_money.record_expense(conn, actor, household_id, _expense_draft(parse(ExpenseIn, payload)),
                                              clock)
        return 201, to_json(expense)
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock, produce=produce)


@router.patch("/households/{household_id}/expenses/{expense_id}", openapi_extra=body_doc(ExpenseEdit))
def edit_expense(household_id: int, expense_id: int, request: Request,
                 session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn),
                 payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_expense(conn, actor, household_id, expense_id)
    data = parse(ExpenseEdit, payload)
    return ok(shared_money.edit_expense(conn, actor, expense_id, data.version, _expense_draft(data), _clock(request)))


@router.delete("/households/{household_id}/expenses/{expense_id}", status_code=204,
               openapi_extra=body_doc(Versioned))
def delete_expense(household_id: int, expense_id: int, request: Request,
                   session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn),
                   payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_expense(conn, actor, household_id, expense_id)
    shared_money.delete_expense(conn, actor, expense_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


@router.get("/households/{household_id}/balances")
def balances(household_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn)):
    households.member(conn, actor_for(request, session), household_id)  # current members only
    page = households.page(conn, actor_for(request, session), household_id, _clock(request))
    nets = {m.user_id: m.net_cents for m in page.members}
    return ok({"nets": [{"user_id": m.user_id, "display_name": m.display_name, "net_cents": m.net_cents}
                        for m in page.members], "plan": simplify(nets)})


@router.get("/households/{household_id}/settlements")
def list_settlements(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: sqlite3.Connection = Depends(get_conn)):
    return ok(households.page(conn, actor_for(request, session), household_id, _clock(request)).settlements)


@router.post("/households/{household_id}/settlements", openapi_extra=body_doc(SettlementIn))
def record_settlement(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor, clock = actor_for(request, session), _clock(request)
    households.member(conn, actor, household_id)

    def produce():
        data = parse(SettlementIn, payload)
        settlement, over = shared_money.record_settlement(conn, actor, household_id, data.payer_user_id,
                                                          data.payee_user_id, data.amount_cents, data.paid_on, clock)
        return 201, to_json({"settlement": settlement, "more_than_suggested": over})
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock, produce=produce)


def _settlement_action(name: str):
    def handler(settlement_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
        actor, clock = actor_for(request, session), _clock(request)
        households.member(conn, actor, shared_money.settlement_household(conn, settlement_id))
        data = parse(ReasonIn, payload)
        if name == "confirm":
            result = shared_money.confirm_settlement(conn, actor, settlement_id, data.version, clock)
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
def list_household_bills(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                         conn: sqlite3.Connection = Depends(get_conn)):
    return ok(shared_money.household_bills(conn, actor_for(request, session), household_id, _clock(request)))


@router.post("/households/{household_id}/bills", openapi_extra=body_doc(HouseholdBillIn))
def create_household_bill(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                          conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    households.owner(conn, actor, household_id)
    data = parse(HouseholdBillIn, payload)
    series = shared_money.add_household_bill(conn, actor, household_id, shared_money.HouseholdBillInput(
        data.name.strip(), data.amount_cents, data.category_id, _rule(data), data.split_method,
        _entries(data.participants)), _clock(request))
    return ok(series, 201)


@router.patch("/household-occurrences/{occurrence_id}", openapi_extra=body_doc(OccurrenceEdit))
def edit_household_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                              conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    shared_money.get_household_occurrence(conn, actor, occurrence_id)
    data = parse(OccurrenceEdit, payload)
    shared_money.edit_household_occurrence(conn, actor, occurrence_id, data.version, data.amount_cents,
                                           data.due_date, _clock(request))
    return ok(shared_money.get_household_occurrence(conn, actor, occurrence_id))


def _household_occurrence_action(name: str):
    def handler(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), payload: Any = Payload):
        actor, clock = actor_for(request, session), _clock(request)
        shared_money.get_household_occurrence(conn, actor, occurrence_id)
        if name == "pay":
            def produce():
                data = parse(PaymentIn, payload)
                expense = shared_money.pay_household_occurrence(conn, actor, occurrence_id, data.version,
                                                                data.paid_on or clock.today(), clock)
                return 201, to_json(expense)
            return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=clock,
                                   produce=produce)
        version = parse(Versioned, payload).version
        if name == "undo":
            shared_money.undo_household_payment(conn, actor, occurrence_id, version, clock)
        else:
            shared_money.skip_household_occurrence(conn, actor, occurrence_id, version, clock,
                                                   skipped=name == "skip")
        return ok(shared_money.get_household_occurrence(conn, actor, occurrence_id))
    handler.__name__ = f"{name}_household_occurrence"
    return handler


for _name in ("pay", "undo", "skip", "unskip"):
    router.add_api_route(f"/household-occurrences/{{occurrence_id}}/{_name}", _household_occurrence_action(_name),
                         methods=["POST"], openapi_extra=body_doc(PaymentIn if _name == "pay" else Versioned))


# Insights ----------------------------------------------------------------------------------------------

def _dashboard_json(view) -> dict:
    safe = view.safe
    return to_json({"today": view.cycle.today, "next_allowance": view.cycle.next_allowance,
                    "days_remaining": view.cycle.days_remaining, "terms": safe.inputs,
                    "discretionary_cents": safe.discretionary_cents, "daily_cents": safe.daily_cents,
                    "shortfall_cents": safe.shortfall_cents,
                    "household_receivables_cents": view.household_receivables_cents,
                    "planned_allowance_cents": view.planned_allowance_cents,
                    "allowance_reminder": view.allowance_reminder})


@router.get("/dashboard")
def get_dashboard(request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    return JSONResponse(_dashboard_json(dashboard(conn, session.user.id, _clock(request))))


@router.get("/dashboard/preview")
def get_preview(request: Request, cost: str = "", session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn)):
    view = dashboard(conn, session.user.id, _clock(request))
    return ok(preview(view.safe, parse_money(cost, field="cost")))


@router.get("/forecast")
def get_forecast(request: Request, session: Session = Depends(require_ready_session),
                 conn: sqlite3.Connection = Depends(get_conn)):
    result = forecast(conn, session.user.id, _clock(request))
    return ok({**to_json(result.forecast), "window_days": result.window_days})


@router.get("/alerts")
def list_alerts(request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn)):
    alerts.evaluate(conn, session.user.id, _clock(request))
    return ok(alerts.list_alerts(conn, actor_for(request, session)))


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_alert(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
               conn: sqlite3.Connection = Depends(get_conn)):
    alerts.mark_read(conn, actor_for(request, session), alert_id, _clock(request))
    return Response(status_code=204)


@router.post("/alerts/{alert_id}/dismiss", status_code=204)
def dismiss_alert(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    alerts.dismiss(conn, actor_for(request, session), alert_id, _clock(request))
    return Response(status_code=204)


@router.get("/activity")
def personal_activity(request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn)):
    return ok(activity.personal_activity(conn, actor_for(request, session)))


@router.get("/households/{household_id}/activity")
def household_activity(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                       conn: sqlite3.Connection = Depends(get_conn)):
    return ok(activity.household_activity(conn, actor_for(request, session), household_id))
