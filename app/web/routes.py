"""Routes that exist before any domain: the health check and the home page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web.templating import templates

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check used by the README smoke test."""
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    today = request.app.state.clock.today()
    timezone = request.app.state.settings.timezone
    return templates.TemplateResponse(request, "home.html", {"today": today, "timezone": timezone})
