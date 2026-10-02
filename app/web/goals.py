"""Savings goal pages: create, edit, protect, release, and archive (FR-14)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import goals as use_cases
from app.identity.api import Session
from app.planning.api import PRIORITIES, validate_goal
from app.shared.dates import parse_iso_date
from app.shared.errors import ValidationError
from app.shared.money import cents_to_input, parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.rendering import redirect, render

router = APIRouter(prefix="/goals")
FIELDS = ["name", "target", "target_date", "priority", "auto_reserve"]
NOTICES = {"saved": "Goal saved.", "protected": "Protected. Safe-to-spend now sets that money aside.",
           "released": "Released. That money counts as spendable again.", "archived": "Goal archived."}


def _parse(errors: dict[str, str], *, name: str, target: str, target_date: str, priority: str,
           auto_reserve: str | None) -> use_cases.GoalInput:
    cents = collect(errors, parse_money, target, field="target")
    day = collect(errors, parse_iso_date, target_date, field="target_date") if target_date.strip() else None
    level = collect(errors, parse_whole_number, priority, field="priority", low=1, high=3,
                    message="Choose high, normal, or low priority.")
    data = use_cases.GoalInput(name.strip(), cents if cents is not None else 1, day, level or 2,
                               auto_reserve is not None)
    try:
        validate_goal(name=data.name, target_cents=data.target_cents, priority=data.priority)
    except ValidationError as error:
        errors.update({field: message for field, message in error.errors.items() if field not in errors})
    return data


def _values(name="", target="", target_date="", priority="2", auto_reserve=None) -> dict:
    return {"name": name, "target": target, "target_date": target_date, "priority": priority,
            "auto_reserve": auto_reserve is not None}


def _page(request: Request, conn: sqlite3.Connection, session: Session, *, errors=None, values=None,
          move_errors=None, notice=None, status_code: int = 200):
    goals = use_cases.list_goals(conn, actor_for(request, session))
    return render(request, "goals.html",
                  {"goals": goals, "errors": errors or {}, "values": values or _values(),
                   "move_errors": move_errors or {}, "priorities": PRIORITIES, "notice": notice},
                  status_code=status_code)


@router.get("")
def index(request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn), done: str = ""):
    return _page(request, conn, session, notice=NOTICES.get(done))


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create(request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), name: str = Form(""), target: str = Form(""),
           target_date: str = Form(""), priority: str = Form("2"), auto_reserve: str | None = Form(None)):
    errors: dict[str, str] = {}
    data = _parse(errors, name=name, target=target, target_date=target_date, priority=priority,
                  auto_reserve=auto_reserve)
    if not errors:
        use_cases.add_goal(conn, actor_for(request, session), data, request.app.state.clock)
        return redirect("/goals?done=saved")
    return _page(request, conn, session, errors=in_form_order(errors, FIELDS),
                 values=_values(name, target, target_date, priority, auto_reserve), status_code=400)


def _move(sign: int, done: str):
    def handler(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), amount: str = Form("")):
        actor = actor_for(request, session)
        use_cases.get_goal(conn, actor, goal_id)  # 404 first (FR-04)
        errors: dict[str, str] = {}
        cents = collect(errors, parse_money, amount, field="amount")
        if not errors:
            try:
                use_cases.move_money(conn, actor, goal_id, sign * cents, request.app.state.clock)
            except ValidationError as error:
                errors.update(error.errors)
        if errors:
            return _page(request, conn, session, move_errors={goal_id: errors["amount"]}, status_code=400)
        return redirect(f"/goals?done={done}")
    return handler


router.add_api_route("/{goal_id}/protect", _move(1, "protected"), methods=["POST"],
                     dependencies=[Depends(verify_csrf)])
router.add_api_route("/{goal_id}/release", _move(-1, "released"), methods=["POST"],
                     dependencies=[Depends(verify_csrf)])


@router.post("/{goal_id}/archive", dependencies=[Depends(verify_csrf)])
def archive(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
            conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.get_goal(conn, actor, goal_id)
    expected = parse_whole_number(version, field="version", low=1, high=10**9, message="Reload the page and try again.")
    use_cases.archive_goal(conn, actor, goal_id, expected, request.app.state.clock)
    return redirect("/goals?done=archived")


def _edit_page(request: Request, goal, *, values: dict, errors=None, status_code: int = 200):
    return render(request, "goal_edit.html", {"goal": goal, "values": values, "errors": errors or {},
                                              "priorities": PRIORITIES}, status_code=status_code)


@router.get("/{goal_id}/edit")
def edit_form(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
              conn: sqlite3.Connection = Depends(get_conn)):
    goal = use_cases.get_goal(conn, actor_for(request, session), goal_id)
    values = {**_values(goal.name, cents_to_input(goal.target_cents),
                        goal.target_date.isoformat() if goal.target_date else "", str(goal.priority),
                        "on" if goal.auto_reserve else None), "version": str(goal.version)}
    return _edit_page(request, goal, values=values)


@router.post("/{goal_id}/edit", dependencies=[Depends(verify_csrf)])
def edit(goal_id: int, request: Request, session: Session = Depends(require_ready_session),
         conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), name: str = Form(""),
         target: str = Form(""), target_date: str = Form(""), priority: str = Form("2"),
         auto_reserve: str | None = Form(None)):
    actor = actor_for(request, session)
    goal = use_cases.get_goal(conn, actor, goal_id)
    errors: dict[str, str] = {}
    expected = collect(errors, parse_whole_number, version, field="version", low=1, high=10**9,
                       message="Reload the page and try again.")
    data = _parse(errors, name=name, target=target, target_date=target_date, priority=priority,
                  auto_reserve=auto_reserve)
    if not errors:
        try:
            use_cases.edit_goal(conn, actor, goal_id, expected, data, request.app.state.clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        values = {**_values(name, target, target_date, priority, auto_reserve), "version": version}
        return _edit_page(request, goal, values=values, errors=in_form_order(errors, FIELDS), status_code=400)
    return redirect("/goals?done=saved")
