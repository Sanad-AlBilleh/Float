"""Planning use cases on an open connection (FR-05, SRS §4.1)."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.planning import repository
from app.planning.rules import validate_planned_allowance, validate_settings
from app.shared.dates import Cycle, cycle_for
from app.shared.errors import ConflictError

SETUP_MESSAGE = "Complete setup first."


@dataclass(frozen=True)
class PlanningSettings:
    user_id: int
    allowance_day: int
    planned_allowance_cents: int
    opening_includes_allowance: bool = False  # the opening balance already holds the first cycle's allowance


def _settings(row: sqlite3.Row) -> PlanningSettings:
    return PlanningSettings(row["user_id"], row["allowance_day"], row["planned_allowance_cents"],
                            bool(row["opening_includes_allowance"]))


def save_settings(conn: sqlite3.Connection, *, user_id: int, allowance_day: int, planned_allowance_cents: int,
                  opening_includes_allowance: bool = False) -> PlanningSettings:
    if repository.get_settings(conn, user_id) is not None:
        raise ConflictError("Setup is already complete.")
    validate_settings(allowance_day=allowance_day, planned_allowance_cents=planned_allowance_cents)
    repository.insert_settings(
        conn, user_id=user_id, allowance_day=allowance_day, planned_allowance_cents=planned_allowance_cents,
        opening_includes_allowance=opening_includes_allowance,
    )
    return PlanningSettings(user_id, allowance_day, planned_allowance_cents, opening_includes_allowance)


def get_settings(conn: sqlite3.Connection, user_id: int) -> PlanningSettings | None:
    row = repository.get_settings(conn, user_id)
    return None if row is None else _settings(row)


def update_planned_allowance(conn: sqlite3.Connection, *, user_id: int,
                             planned_allowance_cents: int) -> PlanningSettings:
    """Only the planned allowance may change after setup (FR-05)."""
    validate_planned_allowance(planned_allowance_cents)
    if repository.update_planned_allowance(conn, user_id=user_id, planned_allowance_cents=planned_allowance_cents) == 0:
        raise ConflictError(SETUP_MESSAGE)
    return get_settings(conn, user_id)


def get_cycle(conn: sqlite3.Connection, *, user_id: int, today: date) -> Cycle:
    settings = get_settings(conn, user_id)
    if settings is None:
        raise ConflictError(SETUP_MESSAGE)
    return cycle_for(today, settings.allowance_day)
