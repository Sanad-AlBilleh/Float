"""The service as a whole: health, request logs, CORS, and the published API description."""

import json
import logging

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, migrate


def test_health_reports_the_database_and_the_version(client, settings):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": settings.git_sha}


def test_health_does_not_depend_on_the_personal_service(client, personal):
    personal.down = True
    assert client.get("/health").status_code == 200


def test_health_is_503_when_the_database_cannot_be_reached(clock, personal):
    broken = Settings(database_url="mssql://nobody:wrong@127.0.0.1:1/nothing", token_secret="s",
                      internal_api_key="k")
    with TestClient(create_app(broken, clock, personal=personal, run_migrations=False)) as client:
        response = client.get("/health")
    assert response.status_code == 503 and response.json()["status"] == "error"


def test_every_request_is_logged_as_one_json_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="float.request"):
        client.get("/health")
    [line] = [json.loads(r.message) for r in caplog.records if r.name == "float.request"]
    assert (line["method"], line["path"], line["status"]) == ("GET", "/health", 200)


def test_cors_allows_only_the_ui_origin(client):
    asked = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,authorization"}
    allowed = client.options("/api/v1/households", headers={"Origin": "http://localhost:8080", **asked})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8080"
    refused = client.options("/api/v1/households", headers={"Origin": "https://evil.example", **asked})
    assert "access-control-allow-origin" not in refused.headers


def test_openapi_lists_health_the_api_and_the_internal_endpoints(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/health" in paths and "/api/v1/households" in paths and "/internal/users/{user_id}/position" in paths
    assert "/api/v1/transactions" not in paths


def test_a_restart_applies_no_migration_twice(settings):
    assert migrate(settings) == []
