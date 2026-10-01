"""Register, log in, log out, and change password (FR-01–03)."""

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request

from app.application import accounts
from app.identity.api import AuthenticationError, LockedOutError, Session
from app.shared.errors import ValidationError
from app.web.deps import current_session, get_conn, require_session, verify_csrf
from app.web.rendering import redirect, render, set_cookie
from app.web.security import SESSION_COOKIE, safe_next

router = APIRouter()


def _max_age(request: Request) -> timedelta:
    return timedelta(days=request.app.state.settings.session_max_days)


def _signed_in(request: Request, token: str, target: str):
    response = redirect(target)
    set_cookie(response, request, SESSION_COOKIE, token, max_age=int(_max_age(request).total_seconds()))
    return response


@router.get("/register")
def register_form(request: Request, session: Session | None = Depends(current_session)):
    if session is not None:
        return redirect("/")
    return render(request, "auth/register.html")


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register_submit(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    username: str = Form(""),
    display_name: str = Form(""),
    password: str = Form(""),
):
    try:
        _, token = accounts.register_account(
            conn,
            username=username,
            display_name=display_name,
            password=password,
            clock=request.app.state.clock,
            max_age=_max_age(request),
        )
    except ValidationError as error:
        return render(
            request,
            "auth/register.html",
            {"errors": error.errors, "values": {"username": username, "display_name": display_name}},
            status_code=400,
        )
    return _signed_in(request, token, "/")


@router.get("/login")
def login_form(request: Request, session: Session | None = Depends(current_session), next: str = "/"):
    if session is not None:
        return redirect(safe_next(next))
    return render(request, "auth/login.html", {"next": safe_next(next)})


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login_submit(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    username: str = Form(""),
    password: str = Form(""),
    next_path: str = Form("/", alias="next"),
):
    target = safe_next(next_path)
    try:
        _, token = accounts.log_in(
            conn,
            username=username,
            password=password,
            client_address=request.client.host if request.client else "unknown",
            clock=request.app.state.clock,
            max_age=_max_age(request),
        )
    except (AuthenticationError, LockedOutError) as error:
        return render(
            request,
            "auth/login.html",
            {"error": str(error), "values": {"username": username}, "next": target},
            status_code=400,
        )
    return _signed_in(request, token, target)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    accounts.log_out(conn, token=request.cookies.get(SESSION_COOKIE))
    response = redirect("/")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/account")
def account(request: Request, session: Session = Depends(require_session), changed: int = 0):
    return render(request, "account.html", {"changed": bool(changed)})


@router.post("/account/password", dependencies=[Depends(verify_csrf)])
def change_password(
    request: Request,
    session: Session = Depends(require_session),
    conn: sqlite3.Connection = Depends(get_conn),
    current_password: str = Form(""),
    new_password: str = Form(""),
):
    try:
        accounts.change_password(
            conn,
            session=session,
            current_password=current_password,
            new_password=new_password,
            clock=request.app.state.clock,
        )
    except ValidationError as error:
        return render(request, "account.html", {"errors": error.errors}, status_code=400)
    return redirect("/account?changed=1")
