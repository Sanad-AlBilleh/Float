"""The personal service: Identity, Ledger, Planning and Insights behind a JSON API (Assignment 2, ADR-6).

Startup applies this service's migrations once (max one replica on Azure, so they never run twice at the
same time), retrying while an Azure SQL serverless database resumes. Run with
``uvicorn app.main:app --port 8000``.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import errors, health, internal, middleware
from app.api.v1 import routes as api_v1
from app.clients.households import HouseholdsClient
from app.config import Settings, load_settings
from app.db.connection import connect
from app.db.migrations import apply_migrations
from app.shared.clock import Clock, SystemClock

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("float.startup")


def migrate(settings: Settings) -> list[str]:
    conn = connect(settings.database_url, retries=settings.db_connect_retries)
    try:
        return apply_migrations(conn)
    finally:
        conn.close()


def create_app(settings: Settings | None = None, clock: Clock | None = None,
               households: HouseholdsClient | None = None, run_migrations: bool = True) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_migrations:
            migrate(settings)
        logger.info("personal service %s ready", settings.git_sha)
        yield

    app = FastAPI(title="Float personal service", version="2.0.0", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock or SystemClock(settings.tz)
    app.state.households = households or HouseholdsClient(settings.households_url, settings.internal_api_key,
                                                          settings.households_timeout_s)
    middleware.install(app)
    errors.install(app)
    # CORS in the service, not in Container Apps ingress (the ingress setting breaks JSON preflights).
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
                       expose_headers=["X-Request-ID", "Retry-After"])
    app.include_router(health.router)
    app.include_router(api_v1.router)
    app.include_router(internal.router)
    return app


def __getattr__(name: str):
    """``uvicorn app.main:app`` builds the app on first use, so importing this module needs no settings."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
