"""Request IDs, one JSON log line per request on stdout, security headers, and the last-resort 500."""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.api.v1.problems import problem

logger = logging.getLogger("float.request")

SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


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
