"""Savings goal use cases, each in one transaction with its audit event (FR-14, FR-33)."""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from app.application import audit
from app.application.context import Actor
from app.application.setup import current_settings
from app.db.unit_of_work import transaction
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import cycle_for


@dataclass(frozen=True)
class GoalInput:
    name: str
    target_cents: int
    target_date: date | None
    priority: int
    auto_reserve: bool


def goal_plans(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> list[tuple[planning.Goal, planning.GoalPlan]]:
    _, settings = current_settings(conn, actor.user_id)
    return planning.plans(conn, user_id=actor.user_id, cycle=cycle_for(clock.today(), settings.allowance_day))


def get_goal(conn: sqlite3.Connection, actor: Actor, goal_id: int) -> planning.Goal:
    return planning.get_goal(conn, user_id=actor.user_id, goal_id=goal_id)


def _audit(conn, actor: Actor, goal_id: int, action: str, clock: Clock, before=None, after=None) -> None:
    audit.record(conn, actor_user_id=actor.user_id, entity_type="savings_goal", entity_id=goal_id, action=action,
                 now=clock.now_utc(), before=None if before is None else asdict(before),
                 after=None if after is None else asdict(after), request_id=actor.request_id)


def add_goal(conn: sqlite3.Connection, actor: Actor, data: GoalInput, clock: Clock) -> planning.Goal:
    with transaction(conn):
        created = planning.create_goal(conn, user_id=actor.user_id, name=data.name, target_cents=data.target_cents,
                                       target_date=data.target_date, priority=data.priority,
                                       auto_reserve=data.auto_reserve, now=clock.now_utc())
        _audit(conn, actor, created.id, "create", clock, after=created)
    return created


def edit_goal(conn: sqlite3.Connection, actor: Actor, goal_id: int, version: int, data: GoalInput,
              clock: Clock) -> planning.Goal:
    with transaction(conn):
        before = planning.get_goal(conn, user_id=actor.user_id, goal_id=goal_id)
        after = planning.update_goal(conn, user_id=actor.user_id, goal_id=goal_id, version=version, name=data.name,
                                     target_cents=data.target_cents, target_date=data.target_date,
                                     priority=data.priority, auto_reserve=data.auto_reserve)
        _audit(conn, actor, goal_id, "update", clock, before, after)
    return after


def move_money(conn: sqlite3.Connection, actor: Actor, goal_id: int, delta_cents: int, clock: Clock) -> planning.Goal:
    """Protect (positive) or release (negative) money today. No transaction is created (FR-14)."""
    with transaction(conn):
        before = planning.get_goal(conn, user_id=actor.user_id, goal_id=goal_id)
        after = planning.move(conn, user_id=actor.user_id, goal_id=goal_id, delta_cents=delta_cents,
                              moved_on=clock.today(), note="", now=clock.now_utc())
        _audit(conn, actor, goal_id, "protect" if delta_cents > 0 else "release", clock, before, after)
    return after


def archive_goal(conn: sqlite3.Connection, actor: Actor, goal_id: int, version: int, clock: Clock) -> None:
    with transaction(conn):
        before = planning.get_goal(conn, user_id=actor.user_id, goal_id=goal_id)
        after = planning.archive_goal(conn, user_id=actor.user_id, goal_id=goal_id, version=version,
                                      moved_on=clock.today(), now=clock.now_utc())
        _audit(conn, actor, goal_id, "archive", clock, before, after)
