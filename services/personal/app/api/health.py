"""GET /health: 200 when this service can write and read its own database, 503 otherwise (§3).

It never calls the other service: health is about this service's own state only.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db.connection import connect
from app.db.unit_of_work import transaction

router = APIRouter(tags=["health"])


@router.get("/health", responses={200: {"description": "Database readable and writable"},
                                  503: {"description": "Database not reachable or not writable"}})
def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    try:
        conn = connect(settings.database_url, retries=0, login_timeout=5)
        try:
            with transaction(conn):
                conn.execute("UPDATE health_probe SET checked_at = SYSUTCDATETIME() WHERE id = 1")
                row = conn.execute("SELECT checked_at FROM health_probe WHERE id = 1").fetchone()
            if row is None:
                raise RuntimeError("health_probe row missing")
        finally:
            conn.close()
    except Exception as error:  # noqa: BLE001 - any failure means "not healthy"
        return JSONResponse({"status": "error", "db": type(error).__name__, "version": settings.git_sha},
                            status_code=503)
    return JSONResponse({"status": "ok", "db": "ok", "version": settings.git_sha})
