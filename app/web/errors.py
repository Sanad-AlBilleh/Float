"""Map expected errors to friendly HTML pages. Other people's records are simply "not found" (FR-04)."""

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.web.deps import LoginRequired, SetupRequired
from app.web.rendering import redirect, render
from app.web.security import CsrfError


def _page(request: Request, status_code: int, title: str, message: str):
    return render(request, "error.html", {"title": title, "message": message}, status_code=status_code)


def install(app: FastAPI) -> None:
    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return redirect(f"/login?next={quote(target)}")

    @app.exception_handler(SetupRequired)
    async def setup_required(request: Request, exc: SetupRequired):
        return redirect("/setup")

    @app.exception_handler(CsrfError)
    async def csrf_failed(request: Request, exc: CsrfError):
        return _page(request, 403, "Request blocked",
                     "This form expired or was sent from another site. Go back, reload the page, and try again.")

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError):
        return _page(request, 404, "Not found", "That page or record could not be found.")

    @app.exception_handler(PermissionDeniedError)
    async def forbidden(request: Request, exc: PermissionDeniedError):
        return _page(request, 403, "Not allowed", str(exc) or "You do not have permission to do that.")

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError):
        return _page(request, 409, "That has changed", str(exc))

    @app.exception_handler(ValidationError)
    async def invalid(request: Request, exc: ValidationError):
        return _page(request, 400, "Check your input", " ".join(exc.errors.values()))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        titles = {
            404: ("Not found", "That page could not be found."),
            405: ("Not allowed", "That action is not available here."),
        }
        title, message = titles.get(exc.status_code, ("Error", str(exc.detail)))
        return _page(request, exc.status_code, title, message)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return await request_validation_exception_handler(request, exc)
        return _page(request, 400, "Check your input", "Part of that request was not valid.")
