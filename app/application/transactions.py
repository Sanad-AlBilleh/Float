"""Manual transaction use cases, each in one transaction with its audit event (FR-06, FR-33)."""

import sqlite3
from dataclasses import asdict
from datetime import date

from app.application import audit
from app.application.context import Actor
from app.db.unit_of_work import transaction
from app.ledger import api as ledger
from app.shared.clock import Clock
from app.shared.errors import ValidationError


def list_transactions(conn: sqlite3.Connection, actor: Actor, *, limit: int = 50,
                      before: tuple[date, int] | None = None) -> list[ledger.Transaction]:
    return ledger.list_transactions(conn, user_id=actor.user_id, limit=limit, before=before)


def get_transaction(conn: sqlite3.Connection, actor: Actor, transaction_id: int) -> ledger.Transaction:
    return ledger.get_transaction(conn, user_id=actor.user_id, transaction_id=transaction_id)


def draft_problems(conn: sqlite3.Connection, actor: Actor, draft: ledger.TransactionDraft,
                   clock: Clock) -> dict[str, str]:
    """The ledger's rules for a draft, as field messages (empty when valid)."""
    settings = ledger.get_settings(conn, actor.user_id)
    category_ids = {category.id for category in ledger.list_categories(conn)}
    try:
        ledger.validate_draft(draft, tracking_start=settings.tracking_start, today=clock.today(),
                              category_ids=category_ids)
    except ValidationError as error:
        return dict(error.errors)
    return {}


def add_transaction(conn: sqlite3.Connection, actor: Actor, draft: ledger.TransactionDraft,
                    clock: Clock) -> ledger.Transaction:
    with transaction(conn):
        created = ledger.create_manual(
            conn, user_id=actor.user_id, draft=draft, today=clock.today(), now=clock.now_utc()
        )
        audit.record(conn, actor_user_id=actor.user_id, entity_type="transaction", entity_id=created.id,
                     action="create", now=clock.now_utc(), after=asdict(created), request_id=actor.request_id)
    return created


def edit_transaction(conn: sqlite3.Connection, actor: Actor, transaction_id: int, version: int,
                     draft: ledger.TransactionDraft, clock: Clock) -> ledger.Transaction:
    with transaction(conn):
        before = ledger.get_transaction(conn, user_id=actor.user_id, transaction_id=transaction_id)
        after = ledger.update_manual(
            conn, user_id=actor.user_id, transaction_id=transaction_id, version=version, draft=draft,
            today=clock.today(), now=clock.now_utc(),
        )
        audit.record(conn, actor_user_id=actor.user_id, entity_type="transaction", entity_id=transaction_id,
                     action="update", now=clock.now_utc(), before=asdict(before), after=asdict(after),
                     request_id=actor.request_id)
    return after


def remove_transaction(conn: sqlite3.Connection, actor: Actor, transaction_id: int, version: int,
                       clock: Clock) -> None:
    with transaction(conn):
        removed = ledger.delete_manual(conn, user_id=actor.user_id, transaction_id=transaction_id, version=version)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="transaction", entity_id=transaction_id,
                     action="delete", now=clock.now_utc(), before=asdict(removed), request_id=actor.request_id)
