"""Runtime configuration from environment variables and an optional .env file (NFR-06)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """A configuration value is invalid. The message names the variable."""


@dataclass(frozen=True)
class Settings:
    port: int = 8000
    data_dir: Path = Path("data")
    timezone: str = "Europe/Madrid"
    cookie_secure: bool = False
    session_idle_hours: int = 48
    session_max_days: int = 14

    @property
    def db_path(self) -> Path:
        return self.data_dir / "float.sqlite3"

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


def load_settings(env: Mapping[str, str] | None = None, dotenv: Path | None = Path(".env")) -> Settings:
    """Read settings from ``env`` (default ``os.environ``), falling back to ``dotenv`` values."""
    values: dict[str, str] = read_dotenv(dotenv) if dotenv is not None else {}
    values.update(os.environ if env is None else env)
    timezone = values.get("APP_TIMEZONE", "").strip() or "Europe/Madrid"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"APP_TIMEZONE is not a known time zone: {timezone!r}") from None
    return Settings(
        port=_integer(values, "PORT", 8000, 1, 65535),
        data_dir=Path(values.get("DATA_DIR", "").strip() or "data"),
        timezone=timezone,
        cookie_secure=_boolean(values, "COOKIE_SECURE", False),
        session_idle_hours=_integer(values, "SESSION_IDLE_HOURS", 48, 1, 720),
        session_max_days=_integer(values, "SESSION_MAX_DAYS", 14, 1, 90),
    )
