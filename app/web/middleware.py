"""Request IDs, one structured log line per request, security headers, and the 500 page (NFR-10, SRS §9)."""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.web.templating import templates

logger = logging.getLogger("float.request")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
CSP_EXEMPT_PREFIX = "/api/docs"  # Swagger UI loads its scripts and styles from a CDN.


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request.state.request_id = uuid.uuid4().hex
        request.state.user_id = None
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error in request %s", request.state.request_id)
            response = templates.TemplateResponse(
                request,
                "error.html",
                {
                    "title": "Something went wrong",
                    "message": "Float hit an unexpected error. Please try again; if it keeps happening, "
                    "quote the request ID below.",
                    "request_id": request.state.request_id,
                    "current_user": None,
                    "csrf_token": "",
                },
                status_code=500,
            )
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
