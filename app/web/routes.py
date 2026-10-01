"""Routes that exist before any domain: the health check and the home page."""

from fastapi import APIRouter, Depends, Request

from app.identity.api import Session
from app.web.deps import current_session
from app.web.rendering import render

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check used by the README smoke test."""
    return {"status": "ok"}


@router.get("/")
def home(request: Request, session: Session | None = Depends(current_session)):
    today = request.app.state.clock.today()
    timezone = request.app.state.settings.timezone
    return render(request, "home.html", {"today": today, "timezone": timezone})
