"""Household pages: the list, create and join, and one page per household with tabs (FR-17–26)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import households as use_cases
from app.application import shared_money
from app.households.api import SPLIT_METHODS, SplitEntry
from app.identity.api import Session
from app.ledger.api import list_categories
from app.shared.dates import parse_iso_date
from app.shared.errors import ConflictError, ValidationError
from app.shared.money import cents_to_input, parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.rendering import redirect, render

router = APIRouter(prefix="/households")
TABS = ("balances", "expenses", "bills", "settlements", "members", "activity")
NOTICES = {"joined": "Welcome! You joined the household.", "created": "Household created. Invite your flatmates.",
           "saved": "Saved.", "left": "You left the household.", "removed": "Member removed.",
           "revoked": "Invitation revoked.", "archived": "Household archived. It is now read-only history."}


def _number(text: str, field: str = "version") -> int:
    return parse_whole_number(text, field=field, low=1, high=2**63 - 1, message="Reload the page and try again.")


def _index(request: Request, conn: sqlite3.Connection, session: Session, *, errors=None, values=None,
           status_code: int = 200):
    mine = use_cases.my_households(conn, actor_for(request, session))
    return render(request, "households/index.html",
                  {"mine": mine, "errors": errors or {}, "values": values or {"name": "", "code": ""}},
                  status_code=status_code)


@router.get("")
def index(request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn)):
    return _index(request, conn, session)


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create(request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), name: str = Form("")):
    try:
        created = use_cases.create_household(conn, actor_for(request, session), name.strip(), request.app.state.clock)
    except ValidationError as error:
        return _index(request, conn, session, errors=error.errors, values={"name": name, "code": ""}, status_code=400)
    return redirect(f"/households/{created.id}?done=created")


@router.post("/join", dependencies=[Depends(verify_csrf)])
def join(request: Request, session: Session = Depends(require_ready_session),
         conn: sqlite3.Connection = Depends(get_conn), code: str = Form("")):
    try:
        joined = use_cases.join_household(conn, actor_for(request, session), code, request.app.state.clock)
    except ValidationError as error:
        return _index(request, conn, session, errors=error.errors, values={"name": "", "code": code}, status_code=400)
    return redirect(f"/households/{joined.id}")


def household_page(request: Request, conn: sqlite3.Connection, session: Session, household_id: int, *,
                   tab: str = "balances", new_code: str | None = None, notice: str | None = None,
                   errors=None, values=None, status_code: int = 200):
    view = use_cases.page(conn, actor_for(request, session), household_id, request.app.state.clock)
    return render(request, "households/show.html",
                  {"page": view, "tab": tab if tab in TABS else "balances", "new_code": new_code, "notice": notice,
                   "errors": errors or {}, "values": values or {}}, status_code=status_code)


@router.get("/{household_id}")
def show(household_id: int, request: Request, session: Session = Depends(require_ready_session),
         conn: sqlite3.Connection = Depends(get_conn), tab: str = "balances", done: str = ""):
    return household_page(request, conn, session, household_id, tab=tab, notice=NOTICES.get(done))


@router.post("/{household_id}/invitations", dependencies=[Depends(verify_csrf)])
def invite(household_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn)):
    """The code is shown in this response only; it is never stored or put in a URL (FR-18)."""
    code = use_cases.invite(conn, actor_for(request, session), household_id, request.app.state.clock)
    return household_page(request, conn, session, household_id, tab="members", new_code=code)


@router.post("/{household_id}/invitations/{invitation_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke(household_id: int, invitation_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn)):
    use_cases.revoke(conn, actor_for(request, session), household_id, invitation_id, request.app.state.clock)
    return redirect(f"/households/{household_id}?tab=members&done=revoked")


@router.post("/{household_id}/leave", dependencies=[Depends(verify_csrf)])
def leave(household_id: int, request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn)):
    use_cases.leave(conn, actor_for(request, session), household_id, request.app.state.clock)
    return redirect(f"/households/{household_id}?done=left")


@router.post("/{household_id}/members/{user_id}/remove", dependencies=[Depends(verify_csrf)])
def remove(household_id: int, user_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn)):
    use_cases.remove(conn, actor_for(request, session), household_id, user_id, request.app.state.clock)
    return redirect(f"/households/{household_id}?tab=members&done=removed")


@router.post("/{household_id}/transfer", dependencies=[Depends(verify_csrf)])
def transfer(household_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), new_owner: str = Form("")):
    actor = actor_for(request, session)
    use_cases.viewer(conn, actor, household_id)  # 404 for strangers before any parsing
    use_cases.transfer(conn, actor, household_id, _number(version), _number(new_owner, "new_owner"),
                       request.app.state.clock)
    return redirect(f"/households/{household_id}?tab=members&done=saved")


@router.post("/{household_id}/rename", dependencies=[Depends(verify_csrf)])
def rename(household_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), name: str = Form("")):
    actor = actor_for(request, session)
    use_cases.viewer(conn, actor, household_id)
    try:
        use_cases.rename(conn, actor, household_id, _number(version), name.strip(), request.app.state.clock)
    except ValidationError as error:
        return household_page(request, conn, session, household_id, tab="members", errors=error.errors,
                              values={"name": name}, status_code=400)
    return redirect(f"/households/{household_id}?tab=members&done=saved")


@router.post("/{household_id}/archive", dependencies=[Depends(verify_csrf)])
def archive(household_id: int, request: Request, session: Session = Depends(require_ready_session),
            conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.viewer(conn, actor, household_id)
    use_cases.archive(conn, actor, household_id, _number(version), request.app.state.clock)
    return redirect(f"/households/{household_id}?done=archived")


# Shared expenses (FR-20–22) ------------------------------------------------------------------------

EXPENSE_FIELDS = ["amount", "spent_on", "category_id", "description", "one_off", "split_method", "participants",
                  "split"]


def _parse_expense(form, errors: dict[str, str], today) -> tuple[shared_money.ExpenseDraft, dict]:
    """Read the expense form. Failed fields keep placeholders so every other rule is still checked."""
    amount = collect(errors, parse_money, form.get("amount", ""), field="amount")
    spent_on = collect(errors, parse_iso_date, form.get("spent_on", ""), field="spent_on")
    category = collect(errors, parse_whole_number, form.get("category_id", ""), field="category_id", low=1,
                       high=10**6, message="Choose a category.")
    method = form.get("split_method", "equal")
    if method not in SPLIT_METHODS:
        errors["split_method"] = "Choose equal, exact, percentage, or shares."
        method = "equal"
    participants = []
    for raw in form.getlist("participant"):
        number = collect(errors, parse_whole_number, raw, field="participants", low=1, high=2**63 - 1,
                         message="Choose participants from the household's current members.")
        if number is not None and number not in participants:
            participants.append(number)
    if not participants:
        errors["participants"] = "Choose at least one participant."
    entries = []
    for user_id in participants:
        raw = form.get(f"value_{user_id}", "")
        value = None
        if method == "exact":
            value = collect(errors, parse_money, raw, field="split", allow_zero=True)
        elif method == "percentage":  # 33.33 % is 3,333 basis points: the same digits as cents
            value = collect(errors, parse_money, raw, field="split", allow_zero=True)
        elif method == "shares":
            value = collect(errors, parse_whole_number, raw, field="split", low=1, high=100,
                            message="Enter a share between 1 and 100 for each participant.")
        entries.append(SplitEntry(user_id, value))
    draft = shared_money.ExpenseDraft(amount if amount is not None else 1, spent_on or today, category,
                                      form.get("description", "").strip(), form.get("one_off") is not None, method,
                                      tuple(entries))
    values = {"amount": form.get("amount", ""), "spent_on": form.get("spent_on", ""),
              "category_id": form.get("category_id", ""), "description": form.get("description", ""),
              "one_off": form.get("one_off") is not None, "split_method": method, "participants": participants,
              "split_values": {user_id: form.get(f"value_{user_id}", "") for user_id in participants}}
    return draft, values


def _expense_values(expense) -> dict:
    method = expense.split_method
    def shown(value):
        if value is None:
            return ""
        return cents_to_input(value) if method in ("exact", "percentage") else str(value)
    return {"amount": cents_to_input(expense.amount_cents), "spent_on": expense.spent_on.isoformat(),
            "category_id": str(expense.category_id), "description": expense.description, "one_off": expense.one_off,
            "split_method": method, "participants": list(expense.shares),
            "split_values": {user: shown(expense.weights.get(user)) for user in expense.shares},
            "version": str(expense.version)}


def _expense_form(request: Request, conn: sqlite3.Connection, session: Session, household_id: int, *, action: str,
                  values: dict, errors=None, editing=None, conflict: bool = False, status_code: int = 200):
    view = use_cases.page(conn, actor_for(request, session), household_id, request.app.state.clock)
    return render(request, "households/expense_form.html",
                  {"page": view, "action": action, "values": values, "errors": errors or {}, "editing": editing,
                   "conflict": conflict, "categories": list_categories(conn)}, status_code=status_code)


@router.get("/{household_id}/expenses/new")
def new_expense(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn)):
    actor = actor_for(request, session)
    use_cases.member(conn, actor, household_id)
    view = use_cases.page(conn, actor, household_id, request.app.state.clock)
    values = {"amount": "", "spent_on": request.app.state.clock.today().isoformat(), "category_id": "",
              "description": "", "one_off": False, "split_method": "equal",
              "participants": [m.user_id for m in view.active_members], "split_values": {}}
    return _expense_form(request, conn, session, household_id, action=f"/households/{household_id}/expenses/new",
                         values=values)


@router.post("/{household_id}/expenses/new", dependencies=[Depends(verify_csrf)])
async def create_expense(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                         conn: sqlite3.Connection = Depends(get_conn)):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.member(conn, actor, household_id)
    errors: dict[str, str] = {}
    draft, values = _parse_expense(await request.form(), errors, clock.today())
    problems = shared_money.expense_problems(conn, actor, household_id, draft, clock)
    errors = in_form_order({**problems, **errors}, EXPENSE_FIELDS)
    if not errors:
        try:
            shared_money.record_expense(conn, actor, household_id, draft, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return _expense_form(request, conn, session, household_id, action=f"/households/{household_id}/expenses/new",
                             values=values, errors=errors, status_code=400)
    return redirect(f"/households/{household_id}?tab=expenses&done=saved")


@router.get("/{household_id}/expenses/{expense_id}/edit")
def edit_expense_form(household_id: int, expense_id: int, request: Request,
                      session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn)):
    actor = actor_for(request, session)
    use_cases.member(conn, actor, household_id)
    expense = shared_money.get_expense(conn, actor, household_id, expense_id)
    shared_money.check_editable(conn, actor, expense_id)
    return _expense_form(request, conn, session, household_id,
                         action=f"/households/{household_id}/expenses/{expense_id}/edit",
                         values=_expense_values(expense), editing=expense)


@router.post("/{household_id}/expenses/{expense_id}/edit", dependencies=[Depends(verify_csrf)])
async def edit_expense(household_id: int, expense_id: int, request: Request,
                       session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn)):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.member(conn, actor, household_id)
    current = shared_money.get_expense(conn, actor, household_id, expense_id)
    shared_money.check_editable(conn, actor, expense_id)
    form = await request.form()
    errors: dict[str, str] = {}
    version = collect(errors, parse_whole_number, form.get("version", ""), field="version", low=1, high=10**9,
                      message="Reload the page and try again.")
    draft, values = _parse_expense(form, errors, clock.today())
    problems = shared_money.expense_problems(conn, actor, household_id, draft, clock)
    errors = in_form_order({**problems, **errors}, EXPENSE_FIELDS)
    action = f"/households/{household_id}/expenses/{expense_id}/edit"
    if not errors:
        try:
            shared_money.edit_expense(conn, actor, expense_id, version, draft, clock)
        except ValidationError as error:
            errors.update(error.errors)
        except ConflictError:
            latest = shared_money.get_expense(conn, actor, household_id, expense_id)
            return _expense_form(request, conn, session, household_id, action=action,
                                 values=_expense_values(latest), editing=latest, conflict=True, status_code=409)
    if errors:
        return _expense_form(request, conn, session, household_id, action=action,
                             values={**values, "version": form.get("version", "")}, errors=errors, editing=current,
                             status_code=400)
    return redirect(f"/households/{household_id}?tab=expenses&done=saved")


@router.post("/{household_id}/expenses/{expense_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_expense(household_id: int, expense_id: int, request: Request,
                   session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn),
                   version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.member(conn, actor, household_id)
    shared_money.get_expense(conn, actor, household_id, expense_id)
    shared_money.delete_expense(conn, actor, expense_id, _number(version), request.app.state.clock)
    return redirect(f"/households/{household_id}?tab=expenses&done=saved")
