"""Configuration comes from environment variables; secrets have no default (Assignment 2 §7.7)."""

import pytest

from app.config import ConfigError, load_settings

SECRETS = {"DATABASE_URL": "mssql://u:p@db:1433/personal", "TOKEN_SECRET": "t", "INTERNAL_API_KEY": "k"}


def test_defaults_apply_to_everything_but_the_secrets(tmp_path):
    settings = load_settings(SECRETS, dotenv=tmp_path / "missing.env")
    assert (settings.port, settings.households_url, settings.households_timeout_s) == (8000, "http://households:8000", 10.0)
    assert settings.cors_origins == ("http://localhost:8080",) and settings.git_sha == "dev"


def test_reads_every_supported_variable(tmp_path):
    settings = load_settings({**SECRETS, "PORT": "9000", "HOUSEHOLDS_URL": "https://hh.example/",
                              "HOUSEHOLDS_TIMEOUT_S": "1.5", "CORS_ORIGINS": "https://a.example, https://b.example/",
                              "GIT_SHA": "abc123", "SESSION_IDLE_HOURS": "2", "DB_CONNECT_RETRIES": "3"},
                             dotenv=tmp_path / "missing.env")
    assert settings.port == 9000 and settings.households_url == "https://hh.example"
    assert settings.households_timeout_s == 1.5 and settings.cors_origins == ("https://a.example", "https://b.example")
    assert (settings.git_sha, settings.session_idle_hours, settings.db_connect_retries) == ("abc123", 2, 3)


@pytest.mark.parametrize("missing", sorted(SECRETS))
def test_a_missing_secret_stops_the_service(tmp_path, missing):
    env = {key: value for key, value in SECRETS.items() if key != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env, dotenv=tmp_path / "missing.env")


@pytest.mark.parametrize("variable, value", [("PORT", "eighty"), ("HOUSEHOLDS_TIMEOUT_S", "60"),
                                             ("APP_TIMEZONE", "Mars/Olympus")])
def test_invalid_values_fail_with_the_variable_name(tmp_path, variable, value):
    with pytest.raises(ConfigError, match=variable):
        load_settings({**SECRETS, variable: value}, dotenv=tmp_path / "missing.env")


def test_environment_overrides_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("PORT=7000\nGIT_SHA=from-file\n")
    settings = load_settings({**SECRETS, "PORT": "7100"}, dotenv=dotenv)
    assert (settings.port, settings.git_sha) == (7100, "from-file")
