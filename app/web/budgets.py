"""The budgets page: consumption against limits, and forms to set or clear them (FR-16, FR-31)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import budgets as use_cases
from app.identity.api import Session
from app.shared.errors import ValidationError
from app.shared.money import parse_money
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.rendering import redirect, render

router = APIRouter(prefix="/budgets")


def _page(request: Request, conn: sqlite3.Connection, session: Session, *, errors=None, saved=False,
          status_code: int = 200):
    cycle, rows = use_cases.budgets(conn, actor_for(request, session), request.app.state.clock)
    return render(request, "budgets.html", {"cycle": cycle, "rows": rows, "row_errors": errors or {},
                                            "saved": saved}, status_code=status_code)


@router.get("")
def index(request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn), saved: int = 0):
    return _page(request, conn, session, saved=bool(saved))


@router.post("/{category_id}", dependencies=[Depends(verify_csrf)])
def set_limit(category_id: int, request: Request, session: Session = Depends(require_ready_session),
              conn: sqlite3.Connection = Depends(get_conn), limit: str = Form(""), scope: str = Form("template")):
    actor, clock = actor_for(request, session), request.app.state.clock
    try:
        cents = parse_money(limit, field="limit", allow_zero=True) if limit.strip() else None
        use_cases.set_limit(conn, actor, category_id, cents, scope if scope in use_cases.SCOPES else "template",
                            clock)
    except ValidationError as error:
        return _page(request, conn, session, errors={category_id: " ".join(error.errors.values())}, status_code=400)
    return redirect("/budgets?saved=1")
