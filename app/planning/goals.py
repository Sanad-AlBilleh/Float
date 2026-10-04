"""Savings goals: protected money is the sum of dated, append-only movements (FR-14).

Movements never touch the Ledger: protected money stays inside the recorded balance and is
subtracted once, in safe-to-spend (SRS §4.5).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.planning import repository
from app.planning.rules import NAME_LIMIT, GoalPlan, goal_plan, next_cycle_contribution
from app.shared.dates import Cycle
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.money import MAX_CENTS, format_money

SQLITE_MAX_ID = 2**63 - 1
PRIORITIES = {1: "High", 2: "Normal", 3: "Low"}
STALE_MESSAGE = "This goal changed since you opened it. Reload the page and try again."


@dataclass(frozen=True)
class Goal:
    id: int
    user_id: int
    name: str
    target_cents: int
    target_date: date | None
    priority: int
    auto_reserve: bool
    protected_cents: int
    version: int

    @property
    def remaining_cents(self) -> int:
        return self.target_cents - self.protected_cents


def _goal(row: sqlite3.Row) -> Goal:
    return Goal(row["id"], row["user_id"], row["name"], row["target_cents"],
                None if row["target_date"] is None else date.fromisoformat(row["target_date"]), row["priority"],
                bool(row["auto_reserve"]), row["protected_cents"], row["version"])


def validate_goal(*, name: str, target_cents: int, priority: int) -> None:
    errors: dict[str, str] = {}
    if not 1 <= len(name) <= NAME_LIMIT:
        errors["name"] = f"Enter a name of 1 to {NAME_LIMIT} characters."
    if not 1 <= target_cents <= MAX_CENTS:
        errors["target"] = "Enter a target between €0.01 and €1,000,000.00."
    if priority not in PRIORITIES:
        errors["priority"] = "Choose high, normal, or low priority."
    if errors:
        raise ValidationError(errors)


def create_goal(conn: sqlite3.Connection, *, user_id: int, name: str, target_cents: int,
                target_date: date | None = None, priority: int = 2, auto_reserve: bool = False,
                now: datetime) -> Goal:
    validate_goal(name=name, target_cents=target_cents, priority=priority)
    goal_id = repository.insert_goal(conn, user_id=user_id, name=name, target_cents=target_cents,
                                     target_date=target_date, priority=priority, auto_reserve=auto_reserve, now=now)
    return get_goal(conn, user_id=user_id, goal_id=goal_id)


def _row(conn: sqlite3.Connection, *, user_id: int, goal_id: int) -> sqlite3.Row:
    row = repository.get_goal(conn, goal_id) if 1 <= goal_id <= SQLITE_MAX_ID else None
    if row is None or row["user_id"] != user_id:
        raise NotFoundError("No such goal.")
    return row


def get_goal(conn: sqlite3.Connection, *, user_id: int, goal_id: int) -> Goal:
    return _goal(_row(conn, user_id=user_id, goal_id=goal_id))


def _active(conn: sqlite3.Connection, *, user_id: int, goal_id: int) -> Goal:
    row = _row(conn, user_id=user_id, goal_id=goal_id)
    if row["archived_at"] is not None:
        raise ConflictError("This goal is archived.")
    return _goal(row)


def list_goals(conn: sqlite3.Connection, *, user_id: int) -> list[Goal]:
    """Active goals, highest priority first."""
    return [_goal(row) for row in repository.list_goals(conn, user_id=user_id)]


def update_goal(conn: sqlite3.Connection, *, user_id: int, goal_id: int, version: int, name: str, target_cents: int,
                target_date: date | None, priority: int, auto_reserve: bool) -> Goal:
    current = _active(conn, user_id=user_id, goal_id=goal_id)
    validate_goal(name=name, target_cents=target_cents, priority=priority)
    if target_cents < current.protected_cents:
        raise ValidationError.single(
            "target", f"The target cannot be below the {format_money(current.protected_cents)} already protected.")
    if repository.update_goal(conn, goal_id=goal_id, version=version, name=name, target_cents=target_cents,
                              target_date=target_date, priority=priority, auto_reserve=auto_reserve) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_goal(conn, user_id=user_id, goal_id=goal_id)


def move(conn: sqlite3.Connection, *, user_id: int, goal_id: int, delta_cents: int, moved_on: date, note: str,
         now: datetime) -> Goal:
    """Protect (positive) or release (negative) money, keeping protected between 0 and the target."""
    goal = _active(conn, user_id=user_id, goal_id=goal_id)
    if delta_cents == 0 or abs(delta_cents) > MAX_CENTS:
        raise ValidationError.single("amount", "Enter an amount between €0.01 and €1,000,000.00.")
    after = goal.protected_cents + delta_cents
    if after < 0:
        raise ValidationError.single(
            "amount", f"You can release at most the {format_money(goal.protected_cents)} protected.")
    if after > goal.target_cents:
        raise ValidationError.single(
            "amount", f"You can protect at most {format_money(goal.remaining_cents)} more for this goal.")
    repository.insert_movement(conn, goal_id=goal_id, delta_cents=delta_cents, moved_on=moved_on, note=note, now=now)
    return get_goal(conn, user_id=user_id, goal_id=goal_id)


def archive_goal(conn: sqlite3.Connection, *, user_id: int, goal_id: int, version: int, moved_on: date,
                 now: datetime) -> Goal:
    """Release everything still protected, then archive, so protected savings return to zero."""
    goal = _active(conn, user_id=user_id, goal_id=goal_id)
    if goal.version != version:
        raise ConflictError(STALE_MESSAGE)
    if goal.protected_cents:
        repository.insert_movement(conn, goal_id=goal_id, delta_cents=-goal.protected_cents, moved_on=moved_on,
                                   note="Released on archive", now=now)
    if repository.archive_goal(conn, goal_id=goal_id, version=version, now=now) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_goal(conn, user_id=user_id, goal_id=goal_id)


def movements(conn: sqlite3.Connection, *, user_id: int, goal_id: int) -> list[tuple[date, int]]:
    _row(conn, user_id=user_id, goal_id=goal_id)
    return [(date.fromisoformat(row["moved_on"]), row["delta_cents"])
            for row in repository.list_movements(conn, goal_id=goal_id)]


def protected_total(conn: sqlite3.Connection, *, user_id: int) -> int:
    return repository.protected_total(conn, user_id=user_id)


def plans(conn: sqlite3.Connection, *, user_id: int, cycle: Cycle) -> list[tuple[Goal, GoalPlan]]:
    """Each active goal with its contribution plan for ``cycle`` (SRS §4.6)."""
    settings = repository.get_settings(conn, user_id)
    if settings is None:
        return []
    return [
        (goal, goal_plan(target_cents=goal.target_cents, target_date=goal.target_date,
                         movements=movements(conn, user_id=user_id, goal_id=goal.id), cycle=cycle,
                         allowance_day=settings["allowance_day"], auto_reserve=goal.auto_reserve))
        for goal in list_goals(conn, user_id=user_id)
    ]


def goal_plan_reserve(conn: sqlite3.Connection, *, user_id: int, cycle: Cycle) -> int:
    return sum(plan.pending_reserve_cents for goal, plan in plans(conn, user_id=user_id, cycle=cycle)
               if goal.auto_reserve)


def next_cycle_goal_plan(conn: sqlite3.Connection, *, user_id: int, cycle: Cycle) -> int:
    return sum(next_cycle_contribution(plan, target_cents=goal.target_cents, protected_now_cents=goal.protected_cents)
               for goal, plan in plans(conn, user_id=user_id, cycle=cycle) if goal.auto_reserve)
