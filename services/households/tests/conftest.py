"""Shared pytest fixtures for the households service. Tests run against a real SQL Server database, with an
in-memory stand-in for the personal service."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import connect
from app.main import create_app
from app.shared.clock import FixedClock
from tests import dbtest
from tests.fakes import FakePersonal

MADRID = ZoneInfo("Europe/Madrid")
TOKEN_SECRET = "test-token-secret"
INTERNAL_KEY = "test-internal-key"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = dbtest.test_database_url("households")
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
def personal(clock) -> FakePersonal:
    return FakePersonal(today=clock.today())


@pytest.fixture
def settings(database_url) -> Settings:
    return Settings(database_url=database_url, token_secret=TOKEN_SECRET, internal_api_key=INTERNAL_KEY)


@pytest.fixture
def app(settings, clock, conn, personal):
    return create_app(settings, clock, personal=personal, run_migrations=False)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
