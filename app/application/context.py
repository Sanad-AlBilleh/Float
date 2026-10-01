"""Who is acting: used for authorization and recorded in the audit trail."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    user_id: int
    request_id: str | None = None
