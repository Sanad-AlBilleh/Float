"""/api/v1 of the personal service: accounts, setup, transactions, bills, goals, budgets, the dashboard,
alerts and the personal activity feed (FR-34, SRS §8.2). The household routes moved to the households
service (ADR-6). Requests carry ``Authorization: Bearer <token>``; errors are problem+json."""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import (
    actor_for,
    get_conn,
    request_token,
    require_ready_session,
    require_session,
)
from app.api.v1 import idempotency
from app.api.v1.problems import to_json
from app.api.v1.responses import extend, named, obj, returns
from app.api.v1.schemas import (
    Credentials,
    GoalEdit,
    GoalIn,
    LimitIn,
    MovementIn,
    OccurrenceEdit,
    PasswordChange,
    PaymentIn,
    PlannedAllowanceIn,
    Registration,
    SeriesIn,
    SetupIn,
    SplitIn,
    TransactionEdit,
    TransactionIn,
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
    categories,
    goals,
    setup,
    transactions,
)
from app.application.activity import ActivityItem
from app.application.bills import BillRow
from app.application.context import Actor
from app.application.dashboard import dashboard, forecast
from app.db.connection import Connection
from app.identity.api import Session
from app.insights.api import Alert, Forecast, Preview, SafeToSpendInputs, preview
from app.ledger.api import Category, LedgerSettings, Transaction, TransactionDraft
from app.planning.api import BillSeries, Goal, GoalPlan, Occurrence, PlanningSettings
from app.shared.errors import ValidationError
from app.shared.money import parse_money
from app.shared.recurrence import Rule

router = APIRouter(prefix="/api/v1", tags=["v1"])
Payload = Body(default=None)

# Response schemas (see responses.py). Records the routes build as dicts are described here.
SIGNED_IN = named("SignedIn", obj(user=named("User", obj(id=int, username=str, display_name=str)), token=str))
ME = named("Me", obj(id=int, username=str, display_name=str, setup_complete=bool))
SETTINGS = named("Settings", obj(ledger=LedgerSettings, planning=PlanningSettings))
PAYMENT = named("Payment", obj(transaction_id=int, occurrence=Occurrence))
GOALS = {"type": "array", "items": named("GoalWithPlan", extend(Goal, plan=GoalPlan))}
BUDGET_ROW = named("BudgetRow", obj(category_id=int, category=str, consumption_cents=int, limit_cents=int | None,
                                    template_cents=int | None, override_cents=int | None, state=str | None))
DASHBOARD = named("Dashboard", obj(
    today=date, next_allowance=date, days_remaining=int, terms=SafeToSpendInputs, discretionary_cents=int,
    daily_cents=int, shortfall_cents=int, household_receivables_cents=int, planned_allowance_cents=int,
    allowance_reminder=bool, in_household=bool, households_available=bool))
FORECAST = named("ForecastWindow", extend(Forecast, window_days=int))


def ok(value: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(to_json(value), status_code=status)


def _clock(request: Request):
    return request.app.state.clock


def _max_age(request: Request) -> timedelta:
    return timedelta(days=request.app.state.settings.session_max_days)


def _households(request: Request):
    return request.app.state.households


def _signed_in(session: Session, token: str, status: int) -> JSONResponse:
    """The UI keeps the token and sends it as ``Authorization: Bearer <token>``."""
    return ok({"user": {"id": session.user.id, "username": session.user.username,
                        "display_name": session.user.display_name}, "token": token}, status)


def _client_address(request: Request) -> str:
    """Who is logging in, for the per-address lockout. On Azure every request arrives from the Container Apps
    ingress, which appends the caller's address as the last X-Forwarded-For entry; earlier entries come
    from the caller and could be faked, so only the last one is used."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.rsplit(",", 1)[-1].strip()[:64] or "unknown"
    return request.client.host if request.client else "unknown"


def _rule(data: SeriesIn) -> Rule:
    return Rule(data.freq, data.interval, data.anchor_date, until=data.until, count=data.count)


# Auth --------------------------------------------------------------------------------------------------

@router.post("/auth/register", **returns(SIGNED_IN, 201), openapi_extra=body_doc(Registration))
def register(request: Request, conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(Registration, payload)
    session, token = accounts.register_account(conn, username=data.username, display_name=data.display_name,
                                               password=data.password, clock=_clock(request),
                                               max_age=_max_age(request),
                                               token_secret=request.app.state.settings.token_secret)
    return _signed_in(session, token, 201)


@router.post("/auth/login", **returns(SIGNED_IN), openapi_extra=body_doc(Credentials))
def login(request: Request, conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(Credentials, payload)
    session, token = accounts.log_in(conn, username=data.username, password=data.password,
                                     client_address=_client_address(request),
                                     clock=_clock(request), max_age=_max_age(request),
                                     token_secret=request.app.state.settings.token_secret)
    return _signed_in(session, token, 200)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, conn: Connection = Depends(get_conn),
           session: Session = Depends(require_session)):
    accounts.log_out(conn, token=request_token(request))
    return Response(status_code=204)


@router.get("/me", **returns(ME))
def me(session: Session = Depends(require_session), conn: Connection = Depends(get_conn)):
    return ok({"id": session.user.id, "username": session.user.username, "display_name": session.user.display_name,
               "setup_complete": setup.is_setup_complete(conn, session.user.id)})


@router.post("/me/password", status_code=204, openapi_extra=body_doc(PasswordChange))
def change_password(request: Request, session: Session = Depends(require_session),
                    conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(PasswordChange, payload)
    accounts.change_password(conn, session=session, current_password=data.current_password,
                             new_password=data.new_password, clock=_clock(request))
    return Response(status_code=204)


# Setup and settings ------------------------------------------------------------------------------------

@router.post("/setup", **returns(SETTINGS), openapi_extra=body_doc(SetupIn))
def complete_setup(request: Request, session: Session = Depends(require_session),
                   conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(SetupIn, payload)
    setup.complete_setup(conn, actor_for(request, session),
                         setup.SetupInput(data.tracking_start, data.opening_balance_cents, data.allowance_day,
                                          data.planned_allowance_cents, data.allowance_included,
                                          data.monthly_savings_cents), _clock(request))
    return settings(session, conn)


@router.get("/settings", **returns(SETTINGS))
def settings(session: Session = Depends(require_ready_session), conn: Connection = Depends(get_conn)):
    ledger_settings, planning_settings = setup.current_settings(conn, session.user.id)
    return ok({"ledger": ledger_settings, "planning": planning_settings})


@router.patch("/settings", **returns(SETTINGS), openapi_extra=body_doc(PlannedAllowanceIn))
def update_settings(request: Request, session: Session = Depends(require_ready_session),
                    conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(PlannedAllowanceIn, payload)
    setup.update_planned_allowance(conn, actor_for(request, session), data.planned_allowance_cents, _clock(request))
    return settings(session, conn)


# Categories --------------------------------------------------------------------------------------------

@router.get("/categories", **returns(list[Category]))
def list_categories(request: Request, session: Session = Depends(require_session),
                    conn: Connection = Depends(get_conn)):
    """The fixed categories, then the user's own: what the UI offers when recording an expense."""
    return ok(categories.list_categories(conn, actor_for(request, session)))


# Transactions ------------------------------------------------------------------------------------------

def _draft(conn: Connection, actor: Actor, data: TransactionIn) -> TransactionDraft:
    """An expense without a category gets the one its note suggests, exactly as on the form."""
    category_id = data.category_id
    if data.kind == "expense" and category_id is None:
        category_id = transactions.suggested_category(conn, actor, data.note)
        if category_id is None:
            raise ValidationError.single("note", transactions.NOTE_FOR_CATEGORY)
    return TransactionDraft(data.kind, data.amount_cents, data.occurred_on, category_id, data.income_source,
                            data.one_off, data.note.strip())


@router.get("/transactions", **returns(list[Transaction]))
def list_transactions(request: Request, session: Session = Depends(require_ready_session),
                      conn: Connection = Depends(get_conn), limit: int = 50):
    return ok(transactions.list_transactions(conn, actor_for(request, session), limit=max(1, min(limit, 200))))


@router.post("/transactions", **returns(Transaction, 201), openapi_extra=body_doc(TransactionIn))
def create_transaction(request: Request, session: Session = Depends(require_ready_session),
                       conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)

    def produce():
        data = parse(TransactionIn, payload)
        return 201, to_json(transactions.add_transaction(conn, actor, _draft(conn, actor, data), _clock(request)))
    return idempotency.run(conn, request, user_id=actor.user_id, payload=payload, clock=_clock(request),
                           produce=produce)


@router.get("/transactions/{transaction_id}", **returns(Transaction))
def get_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: Connection = Depends(get_conn)):
    return ok(transactions.get_transaction(conn, actor_for(request, session), transaction_id))


@router.patch("/transactions/{transaction_id}", **returns(Transaction), openapi_extra=body_doc(TransactionEdit))
def edit_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    transactions.get_transaction(conn, actor, transaction_id)
    data = parse(TransactionEdit, payload)
    return ok(transactions.edit_transaction(conn, actor, transaction_id, data.version, _draft(conn, actor, data),
                                           _clock(request)))


@router.delete("/transactions/{transaction_id}", status_code=204, openapi_extra=body_doc(Versioned))
def delete_transaction(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
                       conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    transactions.get_transaction(conn, actor, transaction_id)
    transactions.remove_transaction(conn, actor, transaction_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


# Bills --------------------------------------------------------------------------------------------------

@router.get("/bills", **returns(list[BillSeries]))
def list_bills(request: Request, session: Session = Depends(require_ready_session),
               conn: Connection = Depends(get_conn)):
    return ok(bills.overview(conn, actor_for(request, session), _clock(request)).series)


@router.post("/bills", **returns(BillSeries, 201), openapi_extra=body_doc(SeriesIn))
def create_bill(request: Request, session: Session = Depends(require_ready_session),
                conn: Connection = Depends(get_conn), payload: Any = Payload):
    data = parse(SeriesIn, payload)
    series = bills.add_series(conn, actor_for(request, session),
                              bills.SeriesInput(data.name.strip(), data.amount_cents, data.category_id, _rule(data)),
                              _clock(request))
    return ok(series, 201)


@router.post("/bills/{series_id}/end", **returns(BillSeries), openapi_extra=body_doc(Versioned))
def end_bill(series_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    bills.get_series(conn, actor, series_id)
    bills.end_series(conn, actor, series_id, parse(Versioned, payload).version, _clock(request))
    return ok(bills.get_series(conn, actor, series_id))


@router.get("/occurrences", **returns(list[BillRow]))
def list_occurrences(request: Request, session: Session = Depends(require_ready_session),
                     conn: Connection = Depends(get_conn), start: date | None = None,
                     end: date | None = None):
    view = bills.overview(conn, actor_for(request, session), _clock(request))
    return ok(view.in_range(start, end))


@router.patch("/occurrences/{occurrence_id}", **returns(Occurrence), openapi_extra=body_doc(OccurrenceEdit))
def edit_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    bills.get_occurrence(conn, actor, occurrence_id)
    data = parse(OccurrenceEdit, payload)
    bills.edit_occurrence(conn, actor, occurrence_id, data.version, data.amount_cents, data.due_date, _clock(request))
    return ok(bills.get_occurrence(conn, actor, occurrence_id))


@router.post("/occurrences/{occurrence_id}/pay", **returns(PAYMENT, 201), openapi_extra=body_doc(PaymentIn))
def pay_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                   conn: Connection = Depends(get_conn), payload: Any = Payload):
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
                conn: Connection = Depends(get_conn), payload: Any = Payload):
        actor = actor_for(request, session)
        bills.get_occurrence(conn, actor, occurrence_id)
        action(conn, actor, occurrence_id, parse(Versioned, payload).version, _clock(request))
        return ok(bills.get_occurrence(conn, actor, occurrence_id))
    handler.__name__ = f"{name}_occurrence"
    return handler


for _name, _action in (("undo", bills.undo_payment), ("skip", bills.skip_occurrence),
                       ("unskip", bills.unskip_occurrence)):
    router.add_api_route(f"/occurrences/{{occurrence_id}}/{_name}", _occurrence_action(_name, _action),
                         methods=["POST"], openapi_extra=body_doc(Versioned), **returns(Occurrence))


@router.post("/occurrences/{occurrence_id}/split", **returns(BillSeries, 201), openapi_extra=body_doc(SplitIn))
def split_occurrence(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                     conn: Connection = Depends(get_conn), payload: Any = Payload):
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


@router.get("/goals", **returns(GOALS))
def list_goals(request: Request, session: Session = Depends(require_ready_session),
               conn: Connection = Depends(get_conn)):
    return ok([{**to_json(goal), "plan": to_json(plan)}
               for goal, plan in goals.goal_plans(conn, actor_for(request, session), _clock(request))])


@router.post("/goals", **returns(Goal, 201), openapi_extra=body_doc(GoalIn))
def create_goal(request: Request, session: Session = Depends(require_ready_session),
                conn: Connection = Depends(get_conn), payload: Any = Payload):
    return ok(goals.add_goal(conn, actor_for(request, session), _goal_input(parse(GoalIn, payload)), _clock(request)),
              201)


@router.patch("/goals/{goal_id}", **returns(Goal), openapi_extra=body_doc(GoalEdit))
def edit_goal(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
              conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    data = parse(GoalEdit, payload)
    return ok(goals.edit_goal(conn, actor, goal_id, data.version, _goal_input(data), _clock(request)))


@router.post("/goals/{goal_id}/movements", **returns(Goal, 201), openapi_extra=body_doc(MovementIn))
def move_goal_money(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    return ok(goals.move_money(conn, actor, goal_id, parse(MovementIn, payload).delta_cents, _clock(request)), 201)


@router.post("/goals/{goal_id}/archive", status_code=204, openapi_extra=body_doc(Versioned))
def archive_goal(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
                 conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    goals.get_goal(conn, actor, goal_id)
    goals.archive_goal(conn, actor, goal_id, parse(Versioned, payload).version, _clock(request))
    return Response(status_code=204)


def _budget_rows(conn, actor, clock, households):
    _, rows = budgets.budgets(conn, actor, clock, households)
    return [{"category_id": row.category.id, "category": row.category.name, "consumption_cents": row.consumption_cents,
             "limit_cents": row.limit_cents, "template_cents": row.limits.template_cents,
             "override_cents": row.limits.override_cents, "state": row.state} for row in rows]


@router.get("/budgets", **returns({"type": "array", "items": BUDGET_ROW}))
def list_budgets(request: Request, session: Session = Depends(require_ready_session),
                 conn: Connection = Depends(get_conn)):
    return ok(_budget_rows(conn, actor_for(request, session), _clock(request), _households(request)))


@router.put("/budgets/{category_id}", **returns(BUDGET_ROW), openapi_extra=body_doc(LimitIn))
def set_budget(category_id: int, request: Request, session: Session = Depends(require_ready_session),
               conn: Connection = Depends(get_conn), payload: Any = Payload):
    actor = actor_for(request, session)
    data = parse(LimitIn, payload)
    budgets.set_limit(conn, actor, category_id, data.limit_cents, data.scope, _clock(request))
    return ok(next(row for row in _budget_rows(conn, actor, _clock(request), _households(request))
                   if row["category_id"] == category_id))


# Insights ----------------------------------------------------------------------------------------------

def _dashboard_json(view) -> dict:
    safe = view.safe
    return to_json({"today": view.cycle.today, "next_allowance": view.cycle.next_allowance,
                    "days_remaining": view.cycle.days_remaining, "terms": safe.inputs,
                    "discretionary_cents": safe.discretionary_cents, "daily_cents": safe.daily_cents,
                    "shortfall_cents": safe.shortfall_cents,
                    "household_receivables_cents": view.household_receivables_cents,
                    "planned_allowance_cents": view.planned_allowance_cents,
                    "allowance_reminder": view.allowance_reminder, "in_household": view.in_household,
                    "households_available": view.households_available})


@router.get("/dashboard", **returns(DASHBOARD))
def get_dashboard(request: Request, session: Session = Depends(require_ready_session),
                  conn: Connection = Depends(get_conn)):
    return JSONResponse(_dashboard_json(dashboard(conn, session.user.id, _clock(request), _households(request))))


@router.get("/dashboard/preview", **returns(Preview))
def get_preview(request: Request, cost: str = "", session: Session = Depends(require_ready_session),
                conn: Connection = Depends(get_conn)):
    view = dashboard(conn, session.user.id, _clock(request), _households(request))
    return ok(preview(view.safe, parse_money(cost, field="cost")))


@router.get("/forecast", **returns(FORECAST))
def get_forecast(request: Request, session: Session = Depends(require_ready_session),
                 conn: Connection = Depends(get_conn)):
    result = forecast(conn, session.user.id, _clock(request), _households(request))
    return ok({**to_json(result.forecast), "window_days": result.window_days})


@router.get("/alerts", **returns(list[Alert]))
def list_alerts(request: Request, session: Session = Depends(require_ready_session),
                conn: Connection = Depends(get_conn)):
    alerts.evaluate(conn, session.user.id, _clock(request), _households(request))
    return ok(alerts.list_alerts(conn, actor_for(request, session)))


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_alert(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
               conn: Connection = Depends(get_conn)):
    alerts.mark_read(conn, actor_for(request, session), alert_id, _clock(request))
    return Response(status_code=204)


@router.post("/alerts/{alert_id}/dismiss", status_code=204)
def dismiss_alert(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
                  conn: Connection = Depends(get_conn)):
    alerts.dismiss(conn, actor_for(request, session), alert_id, _clock(request))
    return Response(status_code=204)


@router.get("/activity", **returns(list[ActivityItem]))
def personal_activity(request: Request, session: Session = Depends(require_ready_session),
                      conn: Connection = Depends(get_conn)):
    return ok(activity.personal_activity(conn, actor_for(request, session)))
