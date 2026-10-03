"""Bills pages: series, occurrences, pay and undo, skip, and the three kinds of edit (FR-09–13)."""

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, Form, Request

from app.application import bills as use_cases
from app.identity.api import Session
from app.ledger.api import list_categories
from app.shared.dates import parse_iso_date
from app.shared.errors import ValidationError
from app.shared.money import cents_to_input, parse_money
from app.shared.recurrence import FREQUENCIES, MAX_COUNT, Rule
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import collect, in_form_order, parse_whole_number
from app.web.rendering import redirect, render

router = APIRouter(prefix="/bills")
SERIES_FIELDS = ["name", "amount", "category_id", "freq", "interval", "anchor_date", "until", "count"]
NOTICES = {"saved": "Bill saved.", "paid": "Paid. The expense is in your transactions.",
           "undone": "Payment undone. The expense was removed.", "skipped": "Skipped.", "unskipped": "Unskipped.",
           "ended": "Bill ended. Overdue bills stay until you pay or skip them."}


def _version(text: str) -> int:
    return parse_whole_number(text, field="version", low=1, high=10**9, message="Reload the page and try again.")


def _optional(errors: dict[str, str], parse, text: str, **kwargs):
    return collect(errors, parse, text, **kwargs) if (text or "").strip() else None


def _parse_series(errors: dict[str, str], form: dict[str, str], today: date) -> use_cases.SeriesInput:
    """Parse the series form. Failed fields keep placeholders so the domain rules still check the rest."""
    name = form["name"].strip()
    amount = collect(errors, parse_money, form["amount"], field="amount")
    category = collect(errors, parse_whole_number, form["category_id"], field="category_id", low=1, high=10**6,
                       message="Choose a category.")
    return use_cases.SeriesInput(name, amount if amount is not None else 1, category, parse_rule(errors, form, today))


def parse_rule(errors: dict[str, str], form, today: date) -> Rule:
    """The repeat fields of a bill form (shared by personal and household bills)."""
    freq = form["freq"] if form["freq"] in FREQUENCIES else None
    if freq is None:
        errors["freq"] = "Choose once, weekly, or monthly."
    interval = 1 if freq == "once" else collect(errors, parse_whole_number, form["interval"], field="interval",
                                                low=1, high=52, message="Choose an interval between 1 and 52.")
    anchor = collect(errors, parse_iso_date, form["anchor_date"], field="anchor_date")
    until = _optional(errors, parse_iso_date, form["until"], field="until")
    count = _optional(errors, parse_whole_number, form["count"], field="count", low=1, high=MAX_COUNT,
                      message=f"Choose between 1 and {MAX_COUNT} occurrences.")
    rule = Rule("monthly", 1, anchor or today)
    if freq is not None and interval is not None and anchor is not None:
        rule = collect(errors, Rule, freq, interval, anchor, until=until, count=count) or rule
    return rule


def _series_values(series, *, anchor: date | None = None, count: int | None = None) -> dict[str, str]:
    rule = series.rule
    return {"name": series.name, "amount": cents_to_input(series.amount_cents), "category_id": str(series.category_id),
            "freq": rule.freq, "interval": str(rule.interval), "anchor_date": (anchor or rule.anchor).isoformat(),
            "until": "" if rule.until is None or anchor else rule.until.isoformat(),
            "count": "" if count is None else str(count)}


def _form(name: str = "", amount: str = "", category_id: str = "", freq: str = "monthly", interval: str = "1",
          anchor_date: str = "", until: str = "", count: str = "") -> dict[str, str]:
    return {"name": name, "amount": amount, "category_id": category_id, "freq": freq, "interval": interval,
            "anchor_date": anchor_date, "until": until, "count": count}


@router.get("")
def index(request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn), done: str = ""):
    view = use_cases.overview(conn, actor_for(request, session), request.app.state.clock)
    categories = {category.id: category.name for category in list_categories(conn)}
    return render(request, "bills/index.html", {"view": view, "categories": categories,
                                                "notice": NOTICES.get(done)})


@router.get("/new")
def new_form(request: Request, session: Session = Depends(require_ready_session),
             conn: sqlite3.Connection = Depends(get_conn)):
    values = _form(anchor_date=request.app.state.clock.today().isoformat())
    return render(request, "bills/series_form.html", {"values": values, "categories": list_categories(conn)})


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create(request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), name: str = Form(""), amount: str = Form(""),
           category_id: str = Form(""), freq: str = Form(""), interval: str = Form(""),
           anchor_date: str = Form(""), until: str = Form(""), count: str = Form("")):
    actor, clock = actor_for(request, session), request.app.state.clock
    values = _form(name, amount, category_id, freq, interval, anchor_date, until, count)
    parse_errors: dict[str, str] = {}
    data = _parse_series(parse_errors, values, clock.today())
    problems = use_cases.series_problems(conn, actor, name=data.name, amount_cents=data.amount_cents,
                                         category_id=data.category_id, anchor=data.rule.anchor)
    errors = in_form_order({**problems, **parse_errors}, SERIES_FIELDS)
    if not errors:
        try:
            use_cases.add_series(conn, actor, data, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return render(request, "bills/series_form.html",
                      {"values": values, "errors": errors, "categories": list_categories(conn)}, status_code=400)
    return redirect("/bills?done=saved")


def _occurrence_page(request: Request, conn: sqlite3.Connection, session: Session, occurrence_id: int, *,
                     errors=None, values=None, status_code: int = 200):
    actor, clock = actor_for(request, session), request.app.state.clock
    view = use_cases.overview(conn, actor, clock)
    row = next((o for o in view.occurrences if o.id == occurrence_id), None)
    if row is None:  # someone else's, or outside the listed range: look it up so a stranger gets 404
        use_cases.get_occurrence(conn, actor, occurrence_id)
        raise ValidationError.single("occurrence", "That bill is outside the dates Float shows.")
    series = use_cases.get_series(conn, actor, row.series_id)
    remaining = None
    if series.rule.count is not None:
        remaining = series.rule.count - sum(1 for o in view.occurrences
                                            if o.series_id == series.id and o.scheduled_date < row.scheduled_date)
    defaults = {"paid_on": clock.today().isoformat(), "edit_amount": cents_to_input(row.amount_cents),
                "due_date": row.due_date.isoformat(),
                **_series_values(series, anchor=row.scheduled_date, count=remaining)}
    return render(request, "bills/occurrence.html",
                  {"row": row, "series": series, "errors": errors or {}, "values": {**defaults, **(values or {})},
                   "categories": list_categories(conn)}, status_code=status_code)


@router.get("/occurrences/{occurrence_id}")
def occurrence_page(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return _occurrence_page(request, conn, session, occurrence_id)


@router.post("/occurrences/{occurrence_id}/pay", dependencies=[Depends(verify_csrf)])
def pay(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
        conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), paid_on: str = Form("")):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.get_occurrence(conn, actor, occurrence_id)  # 404 first (FR-04)
    errors: dict[str, str] = {}
    day = collect(errors, parse_iso_date, paid_on or clock.today().isoformat(), field="paid_on")
    if not errors:
        try:
            use_cases.pay_occurrence(conn, actor, occurrence_id, _version(version), day, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return _occurrence_page(request, conn, session, occurrence_id, errors=errors, values={"paid_on": paid_on},
                                status_code=400)
    return redirect("/bills?done=paid")


def _simple(action, done: str):
    def handler(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
                conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
        actor = actor_for(request, session)
        use_cases.get_occurrence(conn, actor, occurrence_id)
        action(conn, actor, occurrence_id, _version(version), request.app.state.clock)
        return redirect(f"/bills?done={done}")
    return handler


router.add_api_route("/occurrences/{occurrence_id}/undo", _simple(use_cases.undo_payment, "undone"),
                     methods=["POST"], dependencies=[Depends(verify_csrf)])
router.add_api_route("/occurrences/{occurrence_id}/skip", _simple(use_cases.skip_occurrence, "skipped"),
                     methods=["POST"], dependencies=[Depends(verify_csrf)])
router.add_api_route("/occurrences/{occurrence_id}/unskip", _simple(use_cases.unskip_occurrence, "unskipped"),
                     methods=["POST"], dependencies=[Depends(verify_csrf)])


@router.post("/occurrences/{occurrence_id}/edit", dependencies=[Depends(verify_csrf)])
def edit(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
         conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), amount: str = Form(""),
         due_date: str = Form("")):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.get_occurrence(conn, actor, occurrence_id)
    errors: dict[str, str] = {}
    cents = collect(errors, parse_money, amount, field="amount")
    day = collect(errors, parse_iso_date, due_date, field="due_date")
    if not errors:
        try:
            use_cases.edit_occurrence(conn, actor, occurrence_id, _version(version), cents, day, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        renamed = {("edit_amount" if field == "amount" else field): message for field, message in errors.items()}
        return _occurrence_page(request, conn, session, occurrence_id, errors=renamed,
                                values={"edit_amount": amount, "due_date": due_date}, status_code=400)
    return redirect("/bills?done=saved")


@router.post("/occurrences/{occurrence_id}/split", dependencies=[Depends(verify_csrf)])
def split(occurrence_id: int, request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn), version: str = Form(""), name: str = Form(""),
          amount: str = Form(""), category_id: str = Form(""), freq: str = Form(""), interval: str = Form(""),
          anchor_date: str = Form(""), until: str = Form(""), count: str = Form("")):
    actor, clock = actor_for(request, session), request.app.state.clock
    use_cases.get_occurrence(conn, actor, occurrence_id)
    values = _form(name, amount, category_id, freq, interval, anchor_date, until, count)
    errors: dict[str, str] = {}
    data = _parse_series(errors, values, clock.today())
    if not errors:
        try:
            use_cases.split_series(conn, actor, occurrence_id, _version(version), data, clock)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        return _occurrence_page(request, conn, session, occurrence_id, errors=in_form_order(errors, SERIES_FIELDS),
                                values=values, status_code=400)
    return redirect("/bills?done=saved")


@router.post("/series/{series_id}/end", dependencies=[Depends(verify_csrf)])
def end(series_id: int, request: Request, session: Session = Depends(require_ready_session),
        conn: sqlite3.Connection = Depends(get_conn), version: str = Form("")):
    actor = actor_for(request, session)
    use_cases.get_series(conn, actor, series_id)
    use_cases.end_series(conn, actor, series_id, _version(version), request.app.state.clock)
    return redirect("/bills?done=ended")
