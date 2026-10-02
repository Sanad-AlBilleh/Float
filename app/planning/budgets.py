"""Category budgets: a template for every cycle, or an override for one cycle (FR-16).

A missing override falls back to the template, never to an older cycle's override (SRS §4.1).
Limits only compare against consumption; they never reserve cash.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.planning import repository
from app.planning.rules import validate_limit


@dataclass(frozen=True)
class BudgetLimits:
    template_cents: int | None
    override_cents: int | None

    @property
    def effective_cents(self) -> int | None:
        return self.override_cents if self.override_cents is not None else self.template_cents


def set_template(conn: sqlite3.Connection, *, user_id: int, category_id: int, limit_cents: int | None) -> None:
    """Set the limit for every cycle; ``None`` removes it."""
    if limit_cents is None:
        repository.delete_template(conn, user_id=user_id, category_id=category_id)
        return
    validate_limit(limit_cents)
    repository.upsert_template(conn, user_id=user_id, category_id=category_id, limit_cents=limit_cents)


def set_override(conn: sqlite3.Connection, *, user_id: int, category_id: int, cycle_start: date,
                 limit_cents: int | None) -> None:
    """Set the limit for one cycle only; ``None`` removes it, so the template applies again."""
    if limit_cents is None:
        repository.delete_override(conn, user_id=user_id, category_id=category_id, cycle_start=cycle_start)
        return
    validate_limit(limit_cents)
    repository.upsert_override(conn, user_id=user_id, category_id=category_id, cycle_start=cycle_start,
                               limit_cents=limit_cents)


def budget_limits(conn: sqlite3.Connection, *, user_id: int, cycle_start: date) -> dict[int, BudgetLimits]:
    """Every category with a template or an override this cycle."""
    templates = repository.templates(conn, user_id=user_id)
    overrides = repository.overrides(conn, user_id=user_id, cycle_start=cycle_start)
    return {category: BudgetLimits(templates.get(category), overrides.get(category))
            for category in sorted(set(templates) | set(overrides))}


def effective_limit(conn: sqlite3.Connection, *, user_id: int, category_id: int, cycle_start: date) -> int | None:
    limits = budget_limits(conn, user_id=user_id, cycle_start=cycle_start).get(category_id)
    return None if limits is None else limits.effective_cents
