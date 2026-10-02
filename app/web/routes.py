"""The health check and the home page: a welcome for visitors, the dashboard for signed-in users."""

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.application.dashboard import dashboard, forecast
from app.application.setup import is_setup_complete
from app.identity.api import Session
from app.insights.api import preview
from app.shared.errors import ValidationError
from app.shared.money import parse_money
from app.web.charts import projection_chart
from app.web.deps import current_session, get_conn, require_ready_session
from app.web.rendering import redirect, render

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check used by the README smoke test."""
    return {"status": "ok"}


@router.get("/")
def home(request: Request, session: Session | None = Depends(current_session),
         conn: sqlite3.Connection = Depends(get_conn), cost: str | None = None):
    clock = request.app.state.clock
    if session is None:
        return render(request, "home.html",
                      {"today": clock.today(), "timezone": request.app.state.settings.timezone})
    if not is_setup_complete(conn, session.user.id):
        return redirect("/setup")
    view = dashboard(conn, session.user.id, clock)
    result, errors = None, {}
    if cost is not None:  # FR-29: a read-only what-if, so it is a GET that never writes
        try:
            result = preview(view.safe, parse_money(cost, field="cost"))
        except ValidationError as error:
            errors = error.errors
    return render(request, "dashboard.html",
                  {"view": view, "preview": result, "errors": errors, "values": {"cost": cost or ""}},
                  status_code=400 if errors else 200)


@router.get("/forecast")
def forecast_page(request: Request, session: Session = Depends(require_ready_session),
                  conn: sqlite3.Connection = Depends(get_conn)):
    result = forecast(conn, session.user.id, request.app.state.clock)
    chart = projection_chart(result.forecast.timeline, result.forecast.lowest_expected)
    return render(request, "forecast.html", {"result": result, "f": result.forecast, "chart": chart})
