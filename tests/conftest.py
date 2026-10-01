"""Shared pytest fixtures. Every test gets its own temporary database."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import connect
from app.db.migrations import apply_migrations
from app.main import create_app
from app.shared.clock import FixedClock

MADRID = ZoneInfo("Europe/Madrid")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 9, 30, 10, 0, tzinfo=MADRID), MADRID)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def app(settings, clock):
    return create_app(settings, clock)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_client(app):
    """Extra browsers for multi-user tests; each has its own cookie jar."""
    opened = []

    def factory() -> TestClient:
        browser = TestClient(app)
        browser.__enter__()
        opened.append(browser)
        return browser

    yield factory
    for browser in opened:
        browser.__exit__(None, None, None)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    apply_migrations(connection)
    try:
        yield connection
    finally:
        connection.close()
