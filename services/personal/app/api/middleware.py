"""Request IDs, one JSON log line per request on stdout, security headers, and the last-resort 500.

After a successful write by a signed-in user, the user's alerts are re-evaluated (FR-32), as in A1.
"""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.api.v1.problems import problem
from app.application import alerts
from app.application.setup import is_setup_complete
from app.db.connection import connect

logger = logging.getLogger("float.request")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def _refresh_alerts(request: Request) -> None:
    """In its own transaction after the write committed; a failure is logged, never shown to the user."""
    try:
        conn = connect(request.app.state.settings.database_url, retries=0)
        try:
            if is_setup_complete(conn, request.state.user_id):
                alerts.evaluate(conn, request.state.user_id, request.app.state.clock,
                                request.app.state.households)
        finally:
            conn.close()
    except Exception:
        logger.exception("alert evaluation failed after request %s", request.state.request_id)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.user_id = None
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error in request %s", request.state.request_id)
            response = problem(500, "Something went wrong", "Quote the request ID if it keeps happening.",
                               request_id=request.state.request_id)
        if (request.method in UNSAFE_METHODS and request.url.path.startswith("/api/")
                and 200 <= response.status_code < 300 and getattr(request.state, "user_id", None)):
            _refresh_alerts(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(json.dumps({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "request_id": request.state.request_id,
            "user_id": getattr(request.state, "user_id", None),
        }, sort_keys=True))
        return response
