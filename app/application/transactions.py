"""Manual transaction use cases, each in one transaction with its audit event (FR-06, FR-33)."""

import sqlite3
from dataclasses import asdict
from datetime import date, timedelta

from app.application import audit
from app.application.context import Actor
from app.db.unit_of_work import transaction
from app.insights import api as insights
from app.ledger import api as ledger
from app.shared.clock import Clock
from app.shared.errors import ValidationError


def list_transactions(conn: sqlite3.Connection, actor: Actor, *, limit: int = 50,
                      before: tuple[date, int] | None = None) -> list[ledger.Transaction]:
    return ledger.list_transactions(conn, user_id=actor.user_id, limit=limit, before=before)


def current_balance(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> int:
    return ledger.get_balance(conn, user_id=actor.user_id, as_of=clock.today())


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


UNUSUAL_LOOKBACK = timedelta(days=90)
COMPARABLE_ORIGINS = ("manual", "import")


def unusual_expenses(conn: sqlite3.Connection, actor: Actor, items: list[ledger.Transaction]) -> dict[int, int]:
    """FR-31, SRS §4.8: each unusual expense's ID mapped to its category's typical (median) amount.

    An expense is compared with the user's other manual or imported expenses in its category dated in
    the 90 days before it.
    """
    candidates = [t for t in items if t.kind == "expense" and t.origin in COMPARABLE_ORIGINS]
    if not candidates:
        return {}
    rows = [row for row in ledger.get_expense_rows(
        conn, user_id=actor.user_id, start=min(t.occurred_on for t in candidates) - UNUSUAL_LOOKBACK,
        end_exclusive=max(t.occurred_on for t in candidates)) if row.origin in COMPARABLE_ORIGINS]
    flags: dict[int, int] = {}
    for item in candidates:
        history = [row.amount_cents for row in rows if row.category_id == item.category_id
                   and item.occurred_on - UNUSUAL_LOOKBACK <= row.occurred_on < item.occurred_on]
        if insights.is_unusual(item.amount_cents, history):
            flags[item.id] = insights.lower_median(history)
    return flags
