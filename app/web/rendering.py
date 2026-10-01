"""Render pages with the context every template needs, set cookies, and redirect after posts."""

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.identity.api import new_token
from app.web.security import ANON_CSRF_COOKIE
from app.web.templating import templates


def set_cookie(response: Response, request: Request, name: str, value: str, *, max_age: int | None) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookie_secure,
    )


def render(request: Request, name: str, context: dict[str, Any] | None = None, *,
           status_code: int = 200) -> HTMLResponse:
    """Add the signed-in user, a CSRF token, and the request ID to ``context``.

    Anonymous visitors get a double-submit CSRF cookie the first time a page renders a form token.
    """
    session = getattr(request.state, "session", None)
    issued = None
    if session is not None:
        csrf_token = session.csrf_token
    else:
        csrf_token = request.cookies.get(ANON_CSRF_COOKIE) or ""
        if not csrf_token:
            csrf_token = issued = new_token()
    page: dict[str, Any] = {
        "current_user": session.user if session else None,
        "csrf_token": csrf_token,
        "request_id": getattr(request.state, "request_id", None),
        "errors": {},
        "values": {},
    }
    page.update(context or {})
    response = templates.TemplateResponse(request, name, page, status_code=status_code)
    if issued:
        set_cookie(response, request, ANON_CSRF_COOKIE, issued, max_age=None)
    return response


def redirect(url: str) -> RedirectResponse:
    """Post/redirect/get: a 303 makes the browser load ``url`` with GET."""
    return RedirectResponse(url, status_code=303)
