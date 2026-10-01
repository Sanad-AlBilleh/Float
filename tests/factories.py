"""Create test data directly through domain services: fast, no HTTP involved."""

from datetime import date

from app.identity.api import User, register
from app.ledger.api import Transaction, TransactionDraft, create_manual, save_settings

PASSWORD = "correct horse battery"


def make_user(conn, clock, username: str = "ana", display_name: str | None = None) -> User:
    return register(
        conn, username=username, display_name=display_name or username.title(), password=PASSWORD,
        now=clock.now_utc(),
    )


def start_ledger(conn, clock, user: User, *, tracking_start: date, opening_cents: int = 0):
    return save_settings(
        conn, user_id=user.id, tracking_start=tracking_start, opening_balance_cents=opening_cents,
        today=clock.today(),
    )


def add_expense(conn, clock, user: User, cents: int, on: date, *, category_id: int = 1,
                one_off: bool = False, note: str = "") -> Transaction:
    draft = TransactionDraft("expense", cents, on, category_id=category_id, one_off=one_off, note=note)
    return create_manual(conn, user_id=user.id, draft=draft, today=clock.today(), now=clock.now_utc())


def add_income(conn, clock, user: User, cents: int, on: date, *, source: str = "allowance",
               note: str = "") -> Transaction:
    draft = TransactionDraft("income", cents, on, income_source=source, note=note)
    return create_manual(conn, user_id=user.id, draft=draft, today=clock.today(), now=clock.now_utc())


def complete_setup(conn, clock, user: User, *, tracking_start: date, opening_cents: int = 0,
                   allowance_day: int = 1, planned_cents: int = 75000, allowance_included: bool = False) -> None:
    from app.application.context import Actor
    from app.application.setup import SetupInput, complete_setup as run_setup

    data = SetupInput(tracking_start, opening_cents, allowance_day, planned_cents, allowance_included)
    run_setup(conn, Actor(user.id), data, clock)
