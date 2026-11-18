"""The service as a whole: health, request logs, CORS, auth, and the published API description."""

import json
import logging

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, migrate
from tests.api.helpers import signed_up


def test_health_reports_the_database_and_the_version(client, settings):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": settings.git_sha}


def test_health_is_503_when_the_database_cannot_be_reached(clock, households):
    broken = Settings(database_url="mssql://nobody:wrong@127.0.0.1:1/nothing", token_secret="s",
                      internal_api_key="k")
    with TestClient(create_app(broken, clock, households=households, run_migrations=False)) as client:
        response = client.get("/health")
    assert response.status_code == 503 and response.json()["status"] == "error"


def test_every_request_is_logged_as_one_json_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="float.request"):
        client.get("/health")
    [line] = [json.loads(r.message) for r in caplog.records if r.name == "float.request"]
    assert (line["method"], line["path"], line["status"]) == ("GET", "/health", 200)
    assert line["duration_ms"] >= 0


def test_cors_allows_only_the_ui_origin(client):
    asked = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,authorization"}
    allowed = client.options("/api/v1/transactions", headers={"Origin": "http://localhost:8080", **asked})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8080"
    refused = client.options("/api/v1/transactions", headers={"Origin": "https://evil.example", **asked})
    assert "access-control-allow-origin" not in refused.headers


def test_requests_without_a_token_get_401_problem_json(client):
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 401 and response.headers["content-type"].startswith("application/problem+json")
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer f1.1.9999999999.x.forged"}).status_code == 401


def test_the_internal_api_needs_the_internal_key(client):
    signed_up(client)
    assert client.get("/internal/users", params={"ids": "1"}).status_code == 401
    ok = client.get("/internal/users", params={"ids": "1,99"}, headers={"X-Internal-Key": "test-internal-key"})
    assert ok.status_code == 200 and ok.json() == [{"id": 1, "display_name": "Ana"}]


def test_openapi_lists_health_the_api_and_the_internal_endpoints(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/health" in paths and "/api/v1/transactions" in paths and "/internal/transactions" in paths
    assert not any(path.startswith("/api/v1/households") for path in paths)


def test_a_restart_applies_no_migration_twice(settings):
    assert migrate(settings) == []
