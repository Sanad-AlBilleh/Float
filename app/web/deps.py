"""FastAPI dependencies for HTML routes: per-request connection, current session, login, and CSRF."""

import sqlite3
from collections.abc import Iterator
from datetime import timedelta

from fastapi import Depends, Request

from app.application.context import Actor
from app.application.setup import is_setup_complete
from app.db.connection import connect
from app.identity.api import Session, resolve_session
from app.shared.clock import Clock
from app.web.security import ANON_CSRF_COOKIE, SESSION_COOKIE, UNSAFE_METHODS, CsrfError, same_origin, tokens_match


class LoginRequired(Exception):
    """An anonymous request reached a signed-in page; handled as a redirect to /login."""


class SetupRequired(Exception):
    """A signed-in user without completed setup reached a page that needs it; redirects to /setup."""


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when the response is done."""
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def current_session(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Session | None:
    settings = request.app.state.settings
    session = resolve_session(
        conn,
        token=request.cookies.get(SESSION_COOKIE),
        now=request.app.state.clock.now_utc(),
        idle=timedelta(hours=settings.session_idle_hours),
    )
    request.state.session = session
    request.state.user_id = session.user.id if session else None
    return session


def require_session(session: Session | None = Depends(current_session)) -> Session:
    if session is None:
        raise LoginRequired()
    return session


def require_ready_session(session: Session = Depends(require_session),
                          conn: sqlite3.Connection = Depends(get_conn)) -> Session:
    if not is_setup_complete(conn, session.user.id):
        raise SetupRequired()
    return session


def actor_for(request: Request, session: Session) -> Actor:
    return Actor(session.user.id, getattr(request.state, "request_id", None))


async def verify_csrf(request: Request, session: Session | None = Depends(current_session)) -> None:
    """Unsafe methods need a same-site origin and the session's (or anonymous cookie's) CSRF token."""
    if request.method not in UNSAFE_METHODS:
        return
    if not same_origin(request):
        raise CsrfError()
    submitted = request.headers.get("x-csrf-token")
    if submitted is None:
        value = (await request.form()).get("csrf_token")
        submitted = value if isinstance(value, str) else None
    expected = session.csrf_token if session else request.cookies.get(ANON_CSRF_COOKIE)
    if not tokens_match(submitted, expected):
        raise CsrfError()
