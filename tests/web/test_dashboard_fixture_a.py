"""SRS Fixture A through the browser: Ana's dashboard and forecast on 20 September 2026 (AT-19, AT-22)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.connection import connect
from app.main import create_app
from tests.scenarios.flat_3b import build_flat_3b, fixture_a_clock
from tests.web.helpers import log_in


@pytest.fixture
def ana(tmp_path):
    clock = fixture_a_clock()
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings, clock)
    conn = connect(settings.db_path)
    try:
        build_flat_3b(conn, clock)
    finally:
        conn.close()
    with TestClient(app) as browser:
        assert log_in(browser, "ana").status_code == 303
        yield browser


def test_anas_dashboard(ana):
    page = ana.get("/").text
    for text in ("€500.00", "€120.00", "€12.00", "€50.00", "€10.00", "€308.00", "€28.00 per day",
                 "11 days"):
        assert text in page, text
    assert "€18.00 per day" in ana.get("/?cost=110").text
    assert "€42.00 short" in ana.get("/?cost=350").text


def test_anas_forecast(ana):
    page = ana.get("/forecast").text
    for text in ("€12.00 per day", "25 days", "2026-10-15", "€226.00", "2026-09-30", "€25.61 per day"):
        assert text in page, text


def test_anas_household_page(ana):
    households = ana.get("/households").text
    assert "Flat 3B" in households
    page = ana.get("/households/1").text
    assert "Carla pays Ben €40.00" in page and "Ana pays Ben €10.00" in page
