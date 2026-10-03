"""Household pages: the list, create and join, and one page per household with tabs (FR-17–26)."""

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.application import households as use_cases
from app.identity.api import Session
from app.shared.errors import ValidationError
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.forms import parse_whole_number
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
