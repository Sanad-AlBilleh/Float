"""The health check and the home page: a welcome for visitors, the dashboard for signed-in users."""

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.application.dashboard import dashboard
from app.application.setup import is_setup_complete
from app.identity.api import Session
from app.web.deps import current_session, get_conn
from app.web.rendering import redirect, render

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check used by the README smoke test."""
    return {"status": "ok"}


@router.get("/")
def home(request: Request, session: Session | None = Depends(current_session),
         conn: sqlite3.Connection = Depends(get_conn)):
    clock = request.app.state.clock
    if session is None:
        return render(request, "home.html",
                      {"today": clock.today(), "timezone": request.app.state.settings.timezone})
    if not is_setup_complete(conn, session.user.id):
        return redirect("/setup")
    return render(request, "dashboard.html", {"view": dashboard(conn, session.user.id, clock)})
