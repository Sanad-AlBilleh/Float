"""Collect every field error so a form can be shown again with all its messages at once."""

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
