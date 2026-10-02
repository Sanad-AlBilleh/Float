"""Application factory: one process serving HTML and static files (NFR-01)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, load_settings
from app.db.migrations import initialize_database
from app.shared.clock import Clock, SystemClock
from app.web import auth, bills, errors, middleware, setup, transactions
from app.web.routes import router as web_router

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    """Build the app. Database setup runs here, so a bad path or migration fails at startup."""
    settings = settings or load_settings()
    initialize_database(settings.db_path)
    app = FastAPI(
        title="Float",
        version="0.2.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock(settings.tz)
    middleware.install(app)
    errors.install(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web_router)
    app.include_router(auth.router)
    app.include_router(setup.router)
    app.include_router(transactions.router)
    app.include_router(bills.router)
    return app
