"""Configuration comes from environment variables; secrets have no default (Assignment 2 §7.7)."""

import pytest

from app.config import ConfigError, load_settings

SECRETS = {"DATABASE_URL": "mssql://u:p@db:1433/households", "TOKEN_SECRET": "t", "INTERNAL_API_KEY": "k"}


def test_defaults_apply_to_everything_but_the_secrets(tmp_path):
    settings = load_settings(SECRETS, dotenv=tmp_path / "missing.env")
    assert (settings.port, settings.personal_url, settings.personal_timeout_s) == (8000, "http://personal:8000", 10.0)
    assert settings.cors_origins == ("http://localhost:8080",) and settings.git_sha == "dev"


def test_reads_every_supported_variable(tmp_path):
    settings = load_settings({**SECRETS, "PORT": "9000", "PERSONAL_URL": "https://p.example/",
                              "PERSONAL_TIMEOUT_S": "0.5", "CORS_ORIGINS": "https://ui.example", "GIT_SHA": "abc"},
                             dotenv=tmp_path / "missing.env")
    assert (settings.port, settings.personal_url, settings.personal_timeout_s) == (9000, "https://p.example", 0.5)
    assert (settings.cors_origins, settings.git_sha) == (("https://ui.example",), "abc")


@pytest.mark.parametrize("missing", sorted(SECRETS))
def test_a_missing_secret_stops_the_service(tmp_path, missing):
    with pytest.raises(ConfigError, match=missing):
        load_settings({k: v for k, v in SECRETS.items() if k != missing}, dotenv=tmp_path / "missing.env")


@pytest.mark.parametrize("variable, value", [("PORT", "0"), ("PERSONAL_TIMEOUT_S", "fast")])
def test_invalid_values_fail_with_the_variable_name(tmp_path, variable, value):
    with pytest.raises(ConfigError, match=variable):
        load_settings({**SECRETS, variable: value}, dotenv=tmp_path / "missing.env")
