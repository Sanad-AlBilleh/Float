"""Household pages: the list, create and join, and one page per household with tabs (FR-17–26)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import households as use_cases
from app.application import shared_money
from app.application.activity import household_activity
from app.households.api import SPLIT_METHODS, SplitEntry
from app.identity.api import Session
from app.ledger.api import list_categories
from app.shared.dates import parse_iso_date
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.money import cents_to_input, parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.bills import parse_rule
from app.web.rendering import redirect, render

router = APIRouter(prefix="/households")
TABS = ("balances", "expenses", "bills", "settlements", "members", "activity")
NOTICES = {"joined": "Welcome! You joined the household.", "created": "Household created. Invite your flatmates.",
           "saved": "Saved.", "left": "You left the household.", "removed": "Member removed.",
           "revoked": "Invitation revoked.", "archived": "Household archived. It is now read-only history.",
           "recorded": "Transfer recorded. It counts once the other person confirms it.",
           "over": "Transfer recorded. Note: it is more than the settle-up plan suggests, so they will owe you the rest.",
           "confirmed": "Confirmed. Both ledgers now show the transfer.", "rejected": "Rejected.",
           "cancelled": "Cancelled.", "paid": "Paid. Your share and everyone else's are now in the balances.",
           "undone": "Payment undone.", "skipped": "Skipped.", "unskipped": "Unskipped.",
           "ended": "Bill ended. Bills already due stay until they are paid or skipped."}


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
    actor = actor_for(request, session)
    view = use_cases.page(conn, actor, household_id, request.app.state.clock)
    tab = tab if tab in TABS else "balances"
    bills = shared_money.household_bills(conn, actor, household_id, request.app.state.clock) if tab == "bills" else None
    feed = household_activity(conn, actor, household_id) if tab == "activity" else []
    return render(request, "households/show.html",
                  {"page": view, "tab": tab, "bills": bills, "activity": feed, "new_code": new_code, "notice": notice,
                   "errors": errors or {}, "values": values or {},
                   "page_today": request.app.state.clock.today().isoformat(),
                   "categories": {c.id: c.name for c in list_categories(conn)}}, status_code=status_code)


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


def _parse_expense(form, errors: dict[str, str], today,
                   participants: list[str] | None = None) -> tuple[shared_money.ExpenseDraft, dict]:
    """Read the expense form. Failed fields keep placeholders so every other rule is still checked."""
    amount = collect(errors, parse_money, form.get("amount", ""), field="amount")
    spent_on = collect(errors, parse_iso_date, form.get("spent_on", ""), field="spent_on")
    category = collect(errors, parse_whole_number, form.get("category_id", ""), field="category_id", low=1,
                       high=10**6, message="Choose a category.")
    method = form.get("split_method", "equal")
    if method not in SPLIT_METHODS:
        errors["split_method"] = "Choose equal, exact, percentage, or shares."
        method = "equal"
    raw_participants = participants if participants is not None else form.getlist("participant")
    participants = []
    for raw in raw_participants:
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


# Settlements (FR-24) --------------------------------------------------------------------------------

@router.post("/{household_id}/settlements/new", dependencies=[Depends(verify_csrf)])
def record_settlement(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn), direction: str = Form("paid"),
                      counterparty: str = Form(""), amount: str = Form(""), paid_on: str = Form("")):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.member(conn, actor, household_id)
    errors: dict[str, str] = {}
    other = collect(errors, parse_whole_number, counterparty, field="counterparty", low=1, high=2**63 - 1,
                    message="Choose another current member of the household.")
    cents = collect(errors, parse_money, amount, field="amount")
    day = collect(errors, parse_iso_date, paid_on, field="paid_on")
    over = False
    if not errors:
        payer, payee = (actor.user_id, other) if direction != "received" else (other, actor.user_id)
        try:
            _, over = shared_money.record_settlement(conn, actor, household_id, payer, payee, cents, day, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        values = {"direction": direction, "counterparty": counterparty, "amount": amount, "paid_on": paid_on}
        return household_page(request, conn, session, household_id, tab="settlements",
                              errors=in_form_order(errors, ["direction", "counterparty", "amount", "paid_on"]),
                              values=values, status_code=400)
    return redirect(f"/households/{household_id}?tab=settlements&done={'over' if over else 'recorded'}")


def _settlement_action(action: str):
    def handler(household_id: int, settlement_id: int, request: Request,
                session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn),
                version: str = Form(""), reason: str = Form("")):
        actor, clock = actor_for(request, session), request.app.state.clock
        use_cases.viewer(conn, actor, household_id)
        if shared_money.settlement_household(conn, settlement_id) != household_id:
            raise NotFoundError("No such settlement.")
        expected = _number(version)
        if action == "confirm":
            shared_money.confirm_settlement(conn, actor, settlement_id, expected, clock)
        elif action == "reject":
            shared_money.reject_settlement(conn, actor, settlement_id, expected, reason.strip(), clock)
        else:
            shared_money.cancel_settlement(conn, actor, settlement_id, expected, clock)
        return redirect(f"/households/{household_id}?tab=settlements&done={action}ed".replace("eed", "ed"))
    return handler


for _action in ("confirm", "reject", "cancel"):
    router.add_api_route(f"/{{household_id}}/settlements/{{settlement_id}}/{_action}", _settlement_action(_action),
                         methods=["POST"], dependencies=[Depends(verify_csrf)])


# Household bills (FR-25–26) ---------------------------------------------------------------------------

BILL_FIELDS = ["name", "amount", "category_id", "freq", "interval", "anchor_date", "until", "count", "split_method",
               "participants", "split"]


@router.get("/{household_id}/bills/new")
def new_bill(household_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn)):
    actor = actor_for(request, session)
    use_cases.owner(conn, actor, household_id)
    view = use_cases.page(conn, actor, household_id, request.app.state.clock)
    values = {"name": "", "amount": "", "category_id": "", "freq": "monthly", "interval": "1",
              "anchor_date": request.app.state.clock.today().isoformat(), "until": "", "count": "",
              "split_method": "equal", "participants": [m.user_id for m in view.active_members], "split_values": {}}
    return _bill_form(request, conn, view, values)


def _bill_form(request: Request, conn: sqlite3.Connection, view, values: dict, errors=None, status_code: int = 200):
    return render(request, "households/bill_form.html",
                  {"page": view, "values": values, "errors": errors or {}, "categories": list_categories(conn)},
                  status_code=status_code)


@router.post("/{household_id}/bills/new", dependencies=[Depends(verify_csrf)])
async def create_bill(household_id: int, request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn)):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.owner(conn, actor, household_id)
    form = await request.form()
    errors: dict[str, str] = {}
    draft, values = _parse_expense(
        {"amount": form.get("amount", ""), "spent_on": clock.today().isoformat(), "category_id": form.get("category_id", ""),
         "description": form.get("name", ""), "split_method": form.get("split_method", "equal"),
         **{key: form.get(key) for key in form if key.startswith("value_")}}, errors, clock.today(),
        participants=form.getlist("participant"))
    series_form = {key: form.get(key, "") for key in ("name", "amount", "category_id", "freq", "interval",
                                                      "anchor_date", "until", "count")}
    rule = parse_rule(errors, series_form, clock.today())
    values.update(series_form)
    method = form.get("split_method", "equal")
    data = shared_money.HouseholdBillInput(draft.description, draft.amount_cents, draft.category_id, rule,
                                           method if method in SPLIT_METHODS else "equal", draft.entries)
    problems = shared_money.household_bill_problems(conn, actor, household_id, data, clock)
    errors = {**problems, **errors}
    if not errors:
        try:
            shared_money.add_household_bill(conn, actor, household_id, data, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        view = use_cases.page(conn, actor, household_id, clock)
        return _bill_form(request, conn, view, values, in_form_order(errors, BILL_FIELDS), status_code=400)
    return redirect(f"/households/{household_id}?tab=bills&done=saved")


def _bill_action(action: str):
    async def handler(household_id: int, occurrence_id: int, request: Request,
                      session: Session = Depends(require_ready_session), conn: sqlite3.Connection = Depends(get_conn)):
        actor, clock = actor_for(request, session), request.app.state.clock
        use_cases.viewer(conn, actor, household_id)
        if shared_money.get_household_occurrence(conn, actor, occurrence_id).household_id != household_id:
            raise NotFoundError("No such bill.")
        form = await request.form()
        version = _number(form.get("version", ""))
        try:
            if action == "pay":
                day = parse_iso_date(form.get("paid_on") or clock.today().isoformat(), field="paid_on")
                shared_money.pay_household_occurrence(conn, actor, occurrence_id, version, day, clock)
            elif action == "undo":
                shared_money.undo_household_payment(conn, actor, occurrence_id, version, clock)
            elif action in ("skip", "unskip"):
                shared_money.skip_household_occurrence(conn, actor, occurrence_id, version, clock,
                                                       skipped=action == "skip")
            else:
                cents = parse_money(form.get("amount", ""), field="amount")
                day = parse_iso_date(form.get("due_date", ""), field="due_date")
                shared_money.edit_household_occurrence(conn, actor, occurrence_id, version, cents, day, clock)
        except ValidationError as error:
            return household_page(request, conn, session, household_id, tab="bills", errors=error.errors,
                                  status_code=400)
        done = {"pay": "paid", "undo": "undone", "skip": "skipped", "unskip": "unskipped", "edit": "saved"}[action]
        return redirect(f"/households/{household_id}?tab=bills&done={done}")
    return handler


for _action in ("pay", "undo", "skip", "unskip", "edit"):
    router.add_api_route(f"/{{household_id}}/bills/occurrences/{{occurrence_id}}/{_action}", _bill_action(_action),
                         methods=["POST"], dependencies=[Depends(verify_csrf)])


@router.post("/{household_id}/bills/{series_id}/end", dependencies=[Depends(verify_csrf)])
def end_bill(household_id: int, series_id: int, request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.owner(conn, actor, household_id)
    if shared_money.household_bill_series(conn, actor, series_id).household_id != household_id:
        raise NotFoundError("No such bill.")
    shared_money.end_household_bill(conn, actor, series_id, _number(version), request.app.state.clock)
    return redirect(f"/households/{household_id}?tab=bills&done=ended")
