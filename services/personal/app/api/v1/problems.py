"""RFC 9457 problem details for API errors, and JSON serialization of Float's records (FR-34)."""

import dataclasses
from datetime import date, datetime
from typing import Any

from fastapi.responses import JSONResponse

from app.shared.money import format_money

PROBLEM_TYPE = "application/problem+json"


def problem(status: int, title: str, detail: str = "", errors: dict[str, str] | None = None,
            headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status, **extra}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_TYPE, headers=headers)


def to_json(value: Any) -> Any:
    """Dataclasses become objects; dates are ISO strings; every ``*_cents`` integer gains a ``*_display`` twin."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            result[name] = to_json(item)
            if name.endswith("_cents") and isinstance(item, int) and not isinstance(item, bool):
                result[name.removesuffix("_cents") + "_display"] = format_money(item)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
