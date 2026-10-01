import importlib.util
import logging
from pathlib import Path

import pytest

from app.db.connection import connect
from app.db.migrations import MIGRATIONS_DIR
from app.main import create_app
from app.web.templating import templates

ROOT = Path(__file__).resolve().parents[1]


def load_entry_point():
    spec = importlib.util.spec_from_file_location("float_entry", ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_page_uses_the_injected_clock(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<h1>Float</h1>" in response.text
    assert "2026-09-30" in response.text
    assert "Europe/Madrid" in response.text


def test_stylesheet_is_served(client):
    response = client.get("/static/float.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_openapi_schema_is_published(client):
    assert client.get("/api/openapi.json").json()["info"]["title"] == "Float"


def test_templates_escape_user_text():
    rendered = templates.env.from_string("{{ note }}").render(note="<script>alert(1)</script>")
    assert rendered == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_startup_prepares_the_database_and_survives_restart(settings, clock):
    create_app(settings, clock)
    create_app(settings, clock)  # a restart applies nothing twice
    conn = connect(settings.db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        migrations = len(list(MIGRATIONS_DIR.glob("*.sql")))
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == migrations
        assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 11
    finally:
        conn.close()


def test_entry_point_runs_one_worker_without_reload(monkeypatch, tmp_path):
    entry = load_entry_point()
    calls = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **options: calls.update(options, app=app))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PORT", "8123")
    entry.main()
    assert (calls["host"], calls["port"], calls["workers"], calls["reload"]) == ("0.0.0.0", 8123, 1, False)
    assert (tmp_path / "data" / "float.sqlite3").exists()


def test_entry_point_rejects_invalid_configuration(monkeypatch, capsys):
    entry = load_entry_point()
    monkeypatch.setenv("PORT", "not-a-port")
    with pytest.raises(SystemExit) as exit_info:
        entry.main()
    assert exit_info.value.code == 2
    assert "PORT" in capsys.readouterr().err


def test_entry_point_turns_on_the_request_log(monkeypatch, tmp_path):
    entry = load_entry_point()
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **options: None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    logger = logging.getLogger("float")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    entry.main()
    assert logger.isEnabledFor(logging.INFO)
    assert logger.handlers, "the request log needs a handler when Float runs for real"
