"""Expected errors become RFC 9457 problem+json responses. Non-members are told a household does not exist."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import InternalKeyRequired, LoginRequired
from app.api.v1.problems import problem
from app.clients.personal import PersonalUnavailable
from app.db.connection import DatabaseUnavailable
from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


def install(app: FastAPI) -> None:
    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        return problem(401, "Not signed in", "Log in first.")

    @app.exception_handler(InternalKeyRequired)
    async def internal_only(request: Request, exc: InternalKeyRequired):
        return problem(401, "Internal endpoint", "Only the personal service may call this.")

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError):
        return problem(404, "Not found", "That record could not be found.")

    @app.exception_handler(PermissionDeniedError)
    async def forbidden(request: Request, exc: PermissionDeniedError):
        return problem(403, "Not allowed", str(exc) or "You do not have permission to do that.")

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError):
        return problem(409, "That has changed", str(exc))

    @app.exception_handler(ValidationError)
    async def invalid(request: Request, exc: ValidationError):
        return problem(422, "Check your input", " ".join(exc.errors.values()), exc.errors)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return problem(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        fields = {".".join(str(part) for part in error["loc"][1:]) or "body": error["msg"] for error in exc.errors()}
        return problem(422, "Check your input", "Part of that request was not valid.", fields)

    @app.exception_handler(DatabaseUnavailable)
    async def database_starting(request: Request, exc: DatabaseUnavailable):
        return problem(503, "Starting up", "The database is waking up. Try again in a minute.",
                       headers={"Retry-After": "30"})

    @app.exception_handler(PersonalUnavailable)
    async def ledger_down(request: Request, exc: PersonalUnavailable):
        """The designed partial failure (§3): a clear message, nothing half-saved, never a stack trace."""
        return problem(503, "Ledger unavailable", str(exc), headers={"Retry-After": "30"})
