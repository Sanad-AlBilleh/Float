"""Budgets: this cycle's consumption per category against its effective limit (FR-16, FR-31)."""

import sqlite3
from dataclasses import dataclass

from app.application import audit
from app.application.context import Actor
from app.application.dashboard import share_rows
from app.application.setup import current_settings
from app.db.unit_of_work import transaction
from app.insights import api as insights
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import Cycle, cycle_for
from app.shared.errors import NotFoundError

SCOPES = ("template", "cycle")


@dataclass(frozen=True)
class BudgetRow:
    category: ledger.Category
    consumption_cents: int
    limits: planning.BudgetLimits

    @property
    def limit_cents(self) -> int | None:
        return self.limits.effective_cents

    @property
    def state(self) -> str | None:
        return planning.budget_state(self.consumption_cents, self.limit_cents)

    @property
    def percent_used(self) -> int | None:
        return None if not self.limit_cents else self.consumption_cents * 100 // self.limit_cents


def _cycle(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> Cycle:
    _, settings = current_settings(conn, actor.user_id)
    return cycle_for(clock.today(), settings.allowance_day)


def budgets(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> tuple[Cycle, list[BudgetRow]]:
    cycle = _cycle(conn, actor, clock)
    rows = ledger.get_expense_rows(conn, user_id=actor.user_id, start=cycle.start, end_exclusive=cycle.next_allowance)
    shares = share_rows(conn, actor.user_id, cycle.start, cycle.next_allowance)
    consumption = insights.consumption_by_category(rows, shares)
    limits = planning.budget_limits(conn, user_id=actor.user_id, cycle_start=cycle.start)
    return cycle, [BudgetRow(category, consumption.get(category.id, 0),
                             limits.get(category.id, planning.BudgetLimits(None, None)))
                   for category in ledger.list_categories(conn)]


def set_limit(conn: sqlite3.Connection, actor: Actor, category_id: int, limit_cents: int | None, scope: str,
              clock: Clock) -> None:
    """Set or clear (``None``) a category's limit for every cycle or for this cycle only."""
    if category_id not in {category.id for category in ledger.list_categories(conn)}:
        raise NotFoundError("No such category.")
    with transaction(conn):
        cycle = _cycle(conn, actor, clock)
        if scope == "template":
            planning.set_template(conn, user_id=actor.user_id, category_id=category_id, limit_cents=limit_cents)
        else:
            planning.set_override(conn, user_id=actor.user_id, category_id=category_id, cycle_start=cycle.start,
                                  limit_cents=limit_cents)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="budget", entity_id=category_id,
                     action="clear" if limit_cents is None else "set", now=clock.now_utc(),
                     after={"scope": scope, "cycle_start": cycle.start.isoformat(), "limit_cents": limit_cents},
                     request_id=actor.request_id)
