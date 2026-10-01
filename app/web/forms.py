"""Collect every field error so a form can be shown again with all its messages at once."""

import re
from collections.abc import Callable
from typing import Any

from app.shared.errors import ValidationError


def collect(errors: dict[str, str], parse: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Return ``parse(...)``, or merge its validation errors into ``errors`` and return None."""
    try:
        return parse(*args, **kwargs)
    except ValidationError as error:
        errors.update(error.errors)
        return None


_WHOLE_NUMBER = re.compile(r"[0-9]{1,9}")


def parse_whole_number(text: str | None, *, field: str, low: int, high: int, message: str) -> int:
    """ASCII digits only (``str.isdigit`` would accept characters such as "²")."""
    raw = (text or "").strip()
    if not _WHOLE_NUMBER.fullmatch(raw) or not low <= int(raw) <= high:
        raise ValidationError.single(field, message)
    return int(raw)


def in_form_order(errors: dict[str, str], fields: list[str]) -> dict[str, str]:
    """Errors in the order the fields appear, so the summary reads top to bottom."""
    ordered = {field: errors[field] for field in fields if field in errors}
    ordered.update({field: message for field, message in errors.items() if field not in ordered})
    return ordered
