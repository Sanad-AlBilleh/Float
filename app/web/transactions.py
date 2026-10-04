"""Transaction pages: list, add, edit, and delete manual income and expenses (FR-06–08)."""

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, Form, Request

from app.application import transactions as use_cases
from app.identity.api import Session
from app.ledger.api import KINDS, MANUAL_INCOME_SOURCES, Transaction, TransactionDraft, category_names, list_categories
from app.shared.dates import parse_iso_date
from app.shared.errors import ConflictError, ValidationError
from app.shared.money import cents_to_input, parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.rendering import redirect, render

router = APIRouter(prefix="/transactions")
PAGE_SIZE = 50
LINKED_MESSAGE = "This transaction is managed by its bill, shared expense, or settlement."
FIELDS = ["kind", "amount", "occurred_on", "category_id", "income_source", "one_off", "note", "version"]


def _parse(errors: dict[str, str], *, kind: str, amount: str, occurred_on: str, category_id: str,
           income_source: str, one_off: str | None, note: str, today: date) -> TransactionDraft:
    """Parse the form. A field that fails keeps a harmless placeholder, so the ledger rules can still
    check every other field and the form shows all problems at once."""
    if kind not in KINDS:
        errors["kind"] = "Choose income or expense."
    cents = collect(errors, parse_money, amount, field="amount")
    day = collect(errors, parse_iso_date, occurred_on, field="occurred_on")
    category = None
    if kind == "expense":
        category = collect(errors, parse_whole_number, category_id, field="category_id", low=1, high=10**6,
                           message="Choose a category.")
    return TransactionDraft(
        kind=kind if kind in KINDS else "expense",
        amount_cents=cents if cents is not None else 1,
        occurred_on=day or today,
        category_id=category,
        income_source=(income_source or None) if kind == "income" else None,
        one_off=kind == "expense" and one_off is not None,
        note=note.strip(),
    )


def _problems(conn: sqlite3.Connection, actor, parse_errors: dict[str, str], draft: TransactionDraft,
              clock) -> dict[str, str]:
    problems = use_cases.draft_problems(conn, actor, draft, clock)
    return in_form_order({**problems, **parse_errors}, FIELDS)


def _form(request: Request, conn: sqlite3.Connection, *, action: str, values: dict, errors=None,
          editing: Transaction | None = None, conflict: bool = False, status_code: int = 200):
    return render(
        request,
        "transactions/form.html",
        {"action": action, "values": values, "errors": errors or {}, "editing": editing, "conflict": conflict,
         "categories": list_categories(conn, request.state.session.user.id), "income_sources": MANUAL_INCOME_SOURCES},
        status_code=status_code,
    )


def _values_of(transaction: Transaction) -> dict:
    return _submitted(transaction.kind, cents_to_input(transaction.amount_cents),
                      transaction.occurred_on.isoformat(), str(transaction.category_id or ""),
                      transaction.income_source or "allowance", "on" if transaction.one_off else None,
                      transaction.note, str(transaction.version))


def _submitted(kind, amount, occurred_on, category_id, income_source, one_off, note, version="") -> dict:
    return {"kind": kind, "amount": amount, "occurred_on": occurred_on, "category_id": category_id,
            "income_source": income_source, "one_off": one_off is not None, "note": note, "version": version}


def _parse_cursor(before: str | None) -> tuple[date, int] | None:
    """Read an "older" link of the form YYYY-MM-DD:id; anything malformed shows the first page."""
    if not before:
        return None
    day, _, last_id = before.partition(":")
    try:
        cursor = date.fromisoformat(day), int(last_id[:20])
    except ValueError:
        return None
    return cursor if 1 <= cursor[1] <= 2**63 - 1 else None


@router.get("")
def list_page(request: Request, session: Session = Depends(require_ready_session),
              conn: sqlite3.Connection = Depends(get_conn), before: str | None = None,
              saved: int = 0, deleted: int = 0):
    items = use_cases.list_transactions(conn, actor_for(request, session), limit=PAGE_SIZE + 1,
                                        before=_parse_cursor(before))
    older = None
    if len(items) > PAGE_SIZE:
        items = items[:PAGE_SIZE]
        older = f"{items[-1].occurred_on.isoformat()}:{items[-1].id}"
    categories = category_names(conn)
    balance = use_cases.current_balance(conn, actor_for(request, session), request.app.state.clock)
    unusual = use_cases.unusual_expenses(conn, actor_for(request, session), items)
    return render(request, "transactions/list.html",
                  {"items": items, "categories": categories, "older": older, "saved": bool(saved), "unusual": unusual,
                   "deleted": bool(deleted), "balance": balance})


@router.get("/new")
def new_form(request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn), kind: str = "expense", source: str = "allowance"):
    values = _submitted(kind if kind in KINDS else "expense", "", request.app.state.clock.today().isoformat(), "",
                        source if source in MANUAL_INCOME_SOURCES else "allowance", None, "")
    return _form(request, conn, action="/transactions/new", values=values)


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create(
    request: Request,
    session: Session = Depends(require_ready_session),
    conn: sqlite3.Connection = Depends(get_conn),
    kind: str = Form(""),
    amount: str = Form(""),
    occurred_on: str = Form(""),
    category_id: str = Form(""),
    income_source: str = Form(""),
    one_off: str | None = Form(None),
    note: str = Form(""),
):
    actor, clock = actor_for(request, session), request.app.state.clock
    parse_errors: dict[str, str] = {}
    draft = _parse(parse_errors, kind=kind, amount=amount, occurred_on=occurred_on, category_id=category_id,
                   income_source=income_source, one_off=one_off, note=note, today=clock.today())
    errors = _problems(conn, actor, parse_errors, draft, clock)
    if not errors:
        try:
            use_cases.add_transaction(conn, actor, draft, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        values = _submitted(kind, amount, occurred_on, category_id, income_source, one_off, note)
        return _form(request, conn, action="/transactions/new", values=values, errors=errors, status_code=400)
    return redirect("/transactions?saved=1")


@router.get("/{transaction_id}/edit")
def edit_form(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
              conn: sqlite3.Connection = Depends(get_conn)):
    current = use_cases.get_transaction(conn, actor_for(request, session), transaction_id)
    if not current.directly_editable:
        raise ConflictError(LINKED_MESSAGE)
    return _form(request, conn, action=f"/transactions/{transaction_id}/edit", values=_values_of(current),
                 editing=current)


@router.post("/{transaction_id}/edit", dependencies=[Depends(verify_csrf)])
def update(
    transaction_id: int,
    request: Request,
    session: Session = Depends(require_ready_session),
    conn: sqlite3.Connection = Depends(get_conn),
    kind: str = Form(""),
    amount: str = Form(""),
    occurred_on: str = Form(""),
    category_id: str = Form(""),
    income_source: str = Form(""),
    one_off: str | None = Form(None),
    note: str = Form(""),
    version: str = Form(""),
):
    actor, clock = actor_for(request, session), request.app.state.clock
    current = use_cases.get_transaction(conn, actor, transaction_id)  # 404 before anything else (FR-04)
    if not current.directly_editable:  # refused before the form is even checked (FR-07)
        raise ConflictError(LINKED_MESSAGE)
    parse_errors: dict[str, str] = {}
    expected = collect(parse_errors, parse_whole_number, version, field="version", low=1, high=10**9,
                       message="Reload the page and try again.")
    draft = _parse(parse_errors, kind=kind, amount=amount, occurred_on=occurred_on, category_id=category_id,
                   income_source=income_source, one_off=one_off, note=note, today=clock.today())
    errors = _problems(conn, actor, parse_errors, draft, clock)
    if not errors:
        try:
            use_cases.edit_transaction(conn, actor, transaction_id, expected, draft, clock)
        except ValidationError as error:
            errors.update(error.errors)
        except ConflictError:
            latest = use_cases.get_transaction(conn, actor, transaction_id)
            if not latest.directly_editable:
                raise
            # §6.4: a stale edit shows the latest values so the change can be made again.
            return _form(request, conn, action=f"/transactions/{transaction_id}/edit", values=_values_of(latest),
                         editing=latest, conflict=True, status_code=409)
    if errors:
        values = _submitted(kind, amount, occurred_on, category_id, income_source, one_off, note, version)
        return _form(request, conn, action=f"/transactions/{transaction_id}/edit", values=values, errors=errors,
                     editing=current, status_code=400)
    return redirect("/transactions?saved=1")


@router.post("/{transaction_id}/delete", dependencies=[Depends(verify_csrf)])
def delete(transaction_id: int, request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.get_transaction(conn, actor, transaction_id)  # 404 for someone else's record
    expected = parse_whole_number(version, field="version", low=1, high=10**9,
                                  message="Reload the page and try again.")
    use_cases.remove_transaction(conn, actor, transaction_id, expected, request.app.state.clock)
    return redirect("/transactions?deleted=1")
