"""Expense categories: the fixed eleven plus the user's own (student request, 4 October)."""

import sqlite3
from dataclasses import asdict

from app.application import audit
from app.application.context import Actor
from app.db.unit_of_work import transaction
from app.ledger import api as ledger
from app.shared.clock import Clock


def list_categories(conn: sqlite3.Connection, actor: Actor) -> list[ledger.Category]:
    return ledger.list_categories(conn, actor.user_id)


def add_category(conn: sqlite3.Connection, actor: Actor, name: str, clock: Clock) -> ledger.Category:
    with transaction(conn):
        category = ledger.create_category(conn, user_id=actor.user_id, name=name)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="category", entity_id=category.id,
                     action="create", now=clock.now_utc(), after=asdict(category), request_id=actor.request_id)
    return category
