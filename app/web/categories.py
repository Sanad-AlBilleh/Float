"""The categories page: the fixed categories and a form to add your own."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import categories as use_cases
from app.identity.api import Session
from app.shared.errors import ValidationError
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.rendering import redirect, render

router = APIRouter(prefix="/categories")


def _page(request: Request, conn: sqlite3.Connection, session: Session, *, errors=None, values=None, saved=False,
          status_code: int = 200):
    return render(request, "categories.html",
                  {"categories": use_cases.list_categories(conn, actor_for(request, session)), "errors": errors or {},
                   "values": values or {"name": ""}, "saved": saved}, status_code=status_code)


@router.get("")
def index(request: Request, session: Session = Depends(require_ready_session),
          conn: sqlite3.Connection = Depends(get_conn), saved: int = 0):
    return _page(request, conn, session, saved=bool(saved))


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create(request: Request, session: Session = Depends(require_ready_session),
           conn: sqlite3.Connection = Depends(get_conn), name: str = Form("")):
    try:
        use_cases.add_category(conn, actor_for(request, session), name, request.app.state.clock)
    except ValidationError as error:
        return _page(request, conn, session, errors=error.errors, values={"name": name}, status_code=400)
    return redirect("/categories?saved=1")
