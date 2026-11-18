"""Shared pytest fixtures for the personal service. Tests run against a real SQL Server database."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.clients.households import EMPTY_POSITION, Events
from app.config import Settings
from app.db.connection import connect
from app.main import create_app
from app.shared.clock import FixedClock
from tests import dbtest

MADRID = ZoneInfo("Europe/Madrid")
TOKEN_SECRET = "test-token-secret"
INTERNAL_KEY = "test-internal-key"


class NoHouseholds:
    """Stands in for the households service: the user belongs to no household."""

    def position(self, user_id, *, window_end, horizon_end):
        return EMPTY_POSITION

    def shares(self, user_id, *, start, end_exclusive):
        return []

    def events(self, user_id, *, after):
        return Events(after, (), ())


@pytest.fixture(scope="session")
def database_url() -> str:
    url = dbtest.test_database_url("personal")
    dbtest.prepare(url)
    return url


@pytest.fixture
def conn(database_url):
    connection = connect(database_url, retries=0)
    dbtest.reset(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 30, 10, 0, tzinfo=MADRID), MADRID)


@pytest.fixture
def settings(database_url) -> Settings:
    return Settings(database_url=database_url, token_secret=TOKEN_SECRET, internal_api_key=INTERNAL_KEY)


@pytest.fixture
def households():
    return NoHouseholds()


@pytest.fixture
def app(settings, clock, conn, households):
    return create_app(settings, clock, households=households, run_migrations=False)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_client(app):
    """Extra clients for multi-user tests; each signs in with its own token."""
    opened = []

    def factory() -> TestClient:
        browser = TestClient(app)
        browser.__enter__()
        opened.append(browser)
        return browser

    yield factory
    for browser in opened:
        browser.__exit__(None, None, None)
