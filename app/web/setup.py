"""Setup and settings pages (FR-05)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import setup
from app.identity.api import Session
from app.shared.dates import parse_iso_date
from app.shared.errors import ValidationError
from app.shared.money import cents_to_input, parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, require_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.rendering import redirect, render

router = APIRouter()
SETUP_FIELDS = ["tracking_start", "opening_balance", "allowance_included", "allowance_day", "planned_allowance",
                "monthly_savings"]
ALLOWANCE_QUESTION = "Tell Float whether this cycle's allowance is already in that amount."


@router.get("/setup")
def setup_form(request: Request, session: Session = Depends(require_session),
               conn: sqlite3.Connection = Depends(get_conn)):
    if setup.is_setup_complete(conn, session.user.id):
        return redirect("/")
    today = request.app.state.clock.today()
    values = {"tracking_start": today.isoformat(), "opening_balance": "", "allowance_included": "",
              "allowance_day": "1", "planned_allowance": "750.00", "monthly_savings": ""}
    return render(request, "setup.html", {"values": values})


@router.post("/setup", dependencies=[Depends(verify_csrf)])
def setup_submit(
    request: Request,
    session: Session = Depends(require_session),
    conn: sqlite3.Connection = Depends(get_conn),
    tracking_start: str = Form(""),
    opening_balance: str = Form(""),
    allowance_day: str = Form(""),
    planned_allowance: str = Form(""),
    allowance_included: str = Form(""),
    monthly_savings: str = Form(""),
):
    values = {"tracking_start": tracking_start, "opening_balance": opening_balance,
              "allowance_included": allowance_included, "allowance_day": allowance_day,
              "planned_allowance": planned_allowance, "monthly_savings": monthly_savings}
    errors: dict[str, str] = {}
    start = collect(errors, parse_iso_date, tracking_start, field="tracking_start")
    opening = collect(errors, parse_money, opening_balance, field="opening_balance", allow_zero=True,
                      allow_negative=True)
    day = collect(errors, parse_whole_number, allowance_day, field="allowance_day", low=1, high=31,
                  message="Choose a day between 1 and 31.")
    planned = collect(errors, parse_money, planned_allowance, field="planned_allowance")
    savings = collect(errors, parse_money, monthly_savings, field="monthly_savings", allow_zero=True) \
        if monthly_savings.strip() else 0
    if allowance_included not in ("yes", "no"):
        errors["allowance_included"] = ALLOWANCE_QUESTION
    problems = setup.setup_problems(tracking_start=start, opening_balance_cents=opening, allowance_day=day,
                                    planned_allowance_cents=planned, today=request.app.state.clock.today())
    errors = in_form_order({**problems, **errors}, SETUP_FIELDS)
    if not errors:
        try:
            setup.complete_setup(conn, actor_for(request, session),
                                 setup.SetupInput(start, opening, day, planned, allowance_included == "yes", savings or 0),
                                 request.app.state.clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return render(request, "setup.html", {"errors": errors, "values": values}, status_code=400)
    return redirect("/")


def _settings_page(request: Request, conn: sqlite3.Connection, session: Session, *, errors=None, values=None,
                   saved=False, status_code=200):
    ledger_settings, planning_settings = setup.current_settings(conn, session.user.id)
    values = values or {"planned_allowance": cents_to_input(planning_settings.planned_allowance_cents)}
    return render(request, "settings.html",
                  {"ledger": ledger_settings, "planning": planning_settings, "errors": errors or {},
                   "values": values, "saved": saved},
                  status_code=status_code)


@router.get("/settings")
def settings_page(request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn), saved: int = 0):
    return _settings_page(request, conn, session, saved=bool(saved))


@router.post("/settings/planned-allowance", dependencies=[Depends(verify_csrf)])
def update_planned_allowance(
    request: Request,
    session: Session = Depends(require_ready_session),
    conn: sqlite3.Connection = Depends(get_conn),
    planned_allowance: str = Form(""),
):
    errors: dict[str, str] = {}
    cents = collect(errors, parse_money, planned_allowance, field="planned_allowance")
    if not errors:
        try:
            setup.update_planned_allowance(conn, actor_for(request, session), cents, request.app.state.clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return _settings_page(request, conn, session, errors=errors,
                              values={"planned_allowance": planned_allowance}, status_code=400)
    return redirect("/settings?saved=1")
