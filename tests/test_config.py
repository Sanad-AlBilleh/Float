from pathlib import Path

import pytest

from app.config import ConfigError, Settings, load_settings


def test_defaults_apply_without_environment_or_dotenv(tmp_path):
    settings = load_settings({}, dotenv=tmp_path / "missing.env")
    assert settings == Settings()
    assert settings.db_path == Path("data") / "float.sqlite3"
    assert settings.tz.key == "Europe/Madrid"


def test_reads_every_supported_variable(tmp_path):
    settings = load_settings(
        {
            "PORT": "9000",
            "DATA_DIR": str(tmp_path),
            "APP_TIMEZONE": "UTC",
            "COOKIE_SECURE": "true",
            "SESSION_IDLE_HOURS": "1",
            "SESSION_MAX_DAYS": "2",
        },
        dotenv=None,
    )
    assert settings == Settings(9000, tmp_path, "UTC", True, 1, 2)


def test_environment_overrides_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# local overrides\nPORT=7000\nAPP_TIMEZONE='UTC'\n", encoding="utf-8")
    assert load_settings({}, dotenv=dotenv).port == 7000
    assert load_settings({}, dotenv=dotenv).timezone == "UTC"
    assert load_settings({"PORT": "7100"}, dotenv=dotenv).port == 7100


@pytest.mark.parametrize(
    "env, variable",
    [
        ({"PORT": "abc"}, "PORT"),
        ({"PORT": "0"}, "PORT"),
        ({"PORT": "70000"}, "PORT"),
        ({"APP_TIMEZONE": "Mars/Base"}, "APP_TIMEZONE"),
        ({"COOKIE_SECURE": "maybe"}, "COOKIE_SECURE"),
        ({"SESSION_IDLE_HOURS": "0"}, "SESSION_IDLE_HOURS"),
        ({"SESSION_MAX_DAYS": "91"}, "SESSION_MAX_DAYS"),
    ],
)
def test_invalid_values_fail_with_the_variable_name(env, variable):
    with pytest.raises(ConfigError, match=variable):
        load_settings(env, dotenv=None)


def test_malformed_dotenv_line_is_reported(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("NOT A PAIR\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="line 1"):
        load_settings({}, dotenv=dotenv)
