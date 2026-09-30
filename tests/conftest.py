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
def client(settings, clock):
    with TestClient(create_app(settings, clock)) as test_client:
        yield test_client


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.sqlite3")
    apply_migrations(connection)
    try:
        yield connection
    finally:
        connection.close()
