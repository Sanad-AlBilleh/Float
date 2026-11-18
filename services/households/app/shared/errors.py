"""Expected, user-facing errors raised by rules and services; the web layer maps them to HTTP codes."""

from collections.abc import Mapping
from typing import Self


class FloatError(Exception):
    """An error caused by the request or the data, not a bug in Float."""


class ValidationError(FloatError):
    """One or more fields are invalid. ``errors`` maps each field name to a message."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        if not errors:
            raise ValueError("ValidationError needs at least one field error")
        self.errors: dict[str, str] = dict(errors)
        super().__init__("; ".join(f"{field}: {message}" for field, message in self.errors.items()))

    @classmethod
    def single(cls, field: str, message: str) -> Self:
        return cls({field: message})


class NotFoundError(FloatError):
    """The record does not exist, or it belongs to someone else (FR-04 answers 404 for both)."""


class PermissionDeniedError(FloatError):
    """The caller is a household member but lacks the role for this action (403)."""


class ConflictError(FloatError):
    """The record changed since it was read, or the action no longer applies (409)."""
