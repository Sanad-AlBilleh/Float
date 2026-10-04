"""Request IDs, one structured log line per request, security headers, and the 500 page (NFR-10, SRS §9)."""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse, Response

from app.application import alerts
from app.application.setup import is_setup_complete
from app.db.connection import connect
from app.api.v1.problems import problem
from app.web.errors import error_page
from app.web.security import UNSAFE_METHODS

logger = logging.getLogger("float.request")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
CSP_EXEMPT_PREFIX = "/api/docs"  # Swagger UI loads its scripts and styles from a CDN.
FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")
MAX_FORM_BYTES = 64 * 1024  # SRS §9


def _too_large(request: Request) -> bool:
    """Form posts must declare a Content-Length of at most 64 KB (browsers always send one)."""
    if request.method not in UNSAFE_METHODS:
        return False
    if request.headers.get("content-type", "").split(";")[0].strip().lower() not in FORM_TYPES:
        return False
    length = request.headers.get("content-length", "")
    return not length.isdigit() or int(length) > MAX_FORM_BYTES


def _server_error_page(request: Request) -> Response:
    if request.url.path.startswith("/api/"):
        return problem(500, "Something went wrong", "Float hit an unexpected error. Quote the request ID if it "
                       "keeps happening.", request_id=request.state.request_id)
    try:
        return error_page(request, 500, "Something went wrong",
                          "Float hit an unexpected error. Please try again; if it keeps happening, "
                          "quote the request ID below.")
    except Exception:  # noqa: BLE001 - the last resort must not fail
        return PlainTextResponse(f"Internal server error. Request ID: {request.state.request_id}", status_code=500)


def _refresh_alerts(request: Request) -> None:
    """FR-32: re-evaluate alerts after each successful write, in its own transaction after the write committed.

    A failure here must never undo or hide the user's saved change, so it is logged and ignored.
    """
    try:
        conn = connect(request.app.state.settings.db_path)
        try:
            if is_setup_complete(conn, request.state.user_id):
                alerts.evaluate(conn, request.state.user_id, request.app.state.clock)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("alert evaluation failed after request %s", request.state.request_id)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request.state.request_id = uuid.uuid4().hex
        request.state.user_id = None
        started = time.perf_counter()
        if _too_large(request):
            response = error_page(request, 413, "Form too large",
                                  "That form is too large. Forms are limited to 64 KB.")
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("unhandled error in request %s", request.state.request_id)
                response = _server_error_page(request)
        changed = response.status_code == 303 or (request.url.path.startswith("/api/") and 200 <= response.status_code < 300)
        if request.method in UNSAFE_METHODS and changed and getattr(request.state, "user_id", None):
            _refresh_alerts(request)
        for name, value in SECURITY_HEADERS.items():
            if name == "Content-Security-Policy" and request.url.path.startswith(CSP_EXEMPT_PREFIX):
                continue
            response.headers[name] = value
        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "route": getattr(route, "path", None) or "<unmatched>",
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "user_id": getattr(request.state, "user_id", None),
                },
                sort_keys=True,
            )
        )
        return response
