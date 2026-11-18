"""FastAPI dependencies: a connection per request, the signed-in user, and the clock.

The user comes from the bearer token, checked here with TOKEN_SECRET (app.shared.tokens). This service
never asks the personal service who is calling, so it keeps serving households when that service is down
(Assignment 2 §3, ADR-6).
"""

import hmac
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Request

from app.application.context import Actor
from app.db.connection import Connection, connect
from app.shared.clock import Clock
from app.shared.tokens import bearer, verify

REQUEST_DB_RETRIES = 2


class LoginRequired(Exception):
    """No valid bearer token: 401."""


class InternalKeyRequired(Exception):
    """An /internal call without the shared INTERNAL_API_KEY: 401."""


@dataclass(frozen=True)
class User:
    id: int


@dataclass(frozen=True)
class Session:
    """What the routes need from a sign-in: who it is. Shaped like the personal service's session."""
    user: User


def get_conn(request: Request) -> Iterator[Connection]:
    conn = connect(request.app.state.settings.database_url, retries=REQUEST_DB_RETRIES)
    try:
        yield conn
    finally:
        conn.close()


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def require_user(request: Request) -> Session:
    user_id = verify(request.app.state.settings.token_secret, bearer(request.headers.get("authorization")),
                     now=request.app.state.clock.now_utc())
    if user_id is None:
        raise LoginRequired()
    request.state.user_id = user_id
    return Session(User(user_id))


def actor_for(request: Request, session: Session) -> Actor:
    return Actor(session.user.id, getattr(request.state, "request_id", None))


def require_internal(request: Request) -> None:
    expected = request.app.state.settings.internal_api_key
    given = request.headers.get("x-internal-key", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise InternalKeyRequired()
