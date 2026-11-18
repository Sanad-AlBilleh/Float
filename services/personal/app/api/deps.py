"""FastAPI dependencies: a connection per request, the signed-in user from the bearer token, and the clock.

Assignment 1 used a session cookie and a CSRF token. The UI is now a static site on another origin, so
the browser sends ``Authorization: Bearer <token>`` instead; another site cannot make the browser send
that header, so the CSRF token is no longer needed (ADR-6).
"""

import hmac
from collections.abc import Iterator
from datetime import timedelta

from fastapi import Depends, Request

from app.application.context import Actor
from app.application.setup import is_setup_complete
from app.db.connection import Connection, connect
from app.identity.api import Session, resolve_session
from app.shared.clock import Clock
from app.shared.tokens import bearer

REQUEST_DB_RETRIES = 2  # a request waits a few seconds at most; the UI retries a 503 (Assignment 2 §7.5)


class LoginRequired(Exception):
    """No valid bearer token: 401."""


class SetupRequired(Exception):
    """Signed in, but setup is not complete: 409."""


class InternalKeyRequired(Exception):
    """An /internal call without the shared INTERNAL_API_KEY: 401."""


def get_conn(request: Request) -> Iterator[Connection]:
    """One connection per request, closed when the response is done."""
    conn = connect(request.app.state.settings.database_url, retries=REQUEST_DB_RETRIES)
    try:
        yield conn
    finally:
        conn.close()


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def request_token(request: Request) -> str | None:
    return bearer(request.headers.get("authorization"))


def current_session(request: Request, conn: Connection = Depends(get_conn)) -> Session | None:
    settings = request.app.state.settings
    session = resolve_session(
        conn,
        token=request_token(request),
        now=request.app.state.clock.now_utc(),
        idle=timedelta(hours=settings.session_idle_hours),
    )
    request.state.user_id = session.user.id if session else None
    return session


def require_session(session: Session | None = Depends(current_session)) -> Session:
    if session is None:
        raise LoginRequired()
    return session


def require_ready_session(session: Session = Depends(require_session),
                          conn: Connection = Depends(get_conn)) -> Session:
    if not is_setup_complete(conn, session.user.id):
        raise SetupRequired()
    return session


def actor_for(request: Request, session: Session) -> Actor:
    return Actor(session.user.id, getattr(request.state, "request_id", None))


def require_internal(request: Request) -> None:
    """Only the households service knows INTERNAL_API_KEY; compared in constant time."""
    expected = request.app.state.settings.internal_api_key
    given = request.headers.get("x-internal-key", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise InternalKeyRequired()
