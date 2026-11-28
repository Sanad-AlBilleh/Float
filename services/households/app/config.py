"""Runtime configuration of the households service, from environment variables (Assignment 2 §7.7).

Every variable is listed with its default in system.yaml. Secrets (DATABASE_URL, TOKEN_SECRET,
INTERNAL_API_KEY) have no default: the service refuses to start without them. An optional .env file
is still read for running the service outside Docker.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """A configuration value is invalid. The message names the variable."""


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    port: int = 8000
    timezone: str = "Europe/Madrid"
    token_secret: str = ""
    internal_api_key: str = ""
    cors_origins: tuple[str, ...] = ("http://localhost:8080",)
    git_sha: str = "dev"
    db_connect_retries: int = 8
    personal_url: str = "http://personal:8000"
    personal_timeout_s: float = 2.0

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and # comments. A missing file gives {}."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"{path.name} line {number}: expected KEY=VALUE")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _integer(values: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None
    if not low <= number <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {number}")
    return number


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


def _number(values: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        number = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if not low <= number <= high:
        raise ConfigError(f"{name} must be between {low:g} and {high:g}, got {number:g}")
    return number


def _required(values: Mapping[str, str], name: str) -> str:
    raw = values.get(name, "").strip()
    if not raw:
        raise ConfigError(f"{name} is required (a secret, so it has no default)")
    return raw


def load_settings(env: Mapping[str, str] | None = None, dotenv: Path | None = Path(".env")) -> Settings:
    """Read settings from ``env`` (default ``os.environ``), falling back to ``dotenv`` values."""
    values: dict[str, str] = read_dotenv(dotenv) if dotenv is not None else {}
    values.update(os.environ if env is None else env)
    timezone = values.get("APP_TIMEZONE", "").strip() or "Europe/Madrid"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"APP_TIMEZONE is not a known time zone: {timezone!r}") from None
    origins = tuple(o.strip().rstrip("/") for o in values.get("CORS_ORIGINS", "").split(",") if o.strip())
    return Settings(
        database_url=_required(values, "DATABASE_URL"),
        port=_integer(values, "PORT", 8000, 1, 65535),
        timezone=timezone,
        token_secret=_required(values, "TOKEN_SECRET"),
        internal_api_key=_required(values, "INTERNAL_API_KEY"),
        cors_origins=origins or ("http://localhost:8080",),
        git_sha=values.get("GIT_SHA", "").strip() or "dev",
        db_connect_retries=_integer(values, "DB_CONNECT_RETRIES", 8, 0, 20),
        personal_url=(values.get("PERSONAL_URL", "").strip() or "http://personal:8000").rstrip("/"),
        personal_timeout_s=_number(values, "PERSONAL_TIMEOUT_S", 10.0, 0.1, 30.0),
    )
