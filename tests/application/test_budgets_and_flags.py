"""Budget scopes and the unusual-expense lookback (FR-16, FR-31, SRS §4.8)."""

from datetime import date

from app.application import budgets, transactions
from app.application.context import Actor
from app.ledger.api import list_transactions
from tests.factories import add_expense, complete_setup, make_user

EATING_OUT = 2


def test_limits_are_saved_to_the_chosen_scope(conn, clock):
    user = make_user(conn, clock)
    complete_setup(conn, clock, user, tracking_start=date(2026, 9, 1))
    actor = Actor(user.id)
    budgets.set_limit(conn, actor, 1, 5000, "template", clock)
    budgets.set_limit(conn, actor, 2, 1000, "cycle", clock)
    _, rows = budgets.budgets(conn, actor, clock)
    by_id = {row.category.id: row.limits for row in rows}
    assert (by_id[1].template_cents, by_id[1].override_cents) == (5000, None)
    assert (by_id[2].template_cents, by_id[2].override_cents) == (None, 1000)
    audit = conn.execute("SELECT action, after_json FROM audit_events WHERE entity_type = 'budget'").fetchall()
    assert len(audit) == 2 and '"scope": "cycle"' in audit[1]["after_json"]


def test_only_the_last_90_days_count_as_history(conn, clock):
    user = make_user(conn, clock)
    complete_setup(conn, clock, user, tracking_start=date(2026, 5, 1))
    for day, cents in zip(range(1, 9), (800, 900, 1000, 1000, 1100, 1200, 1300, 1500)):
        add_expense(conn, clock, user, cents, date(2026, 6, day), category_id=EATING_OUT)  # over 90 days before
    add_expense(conn, clock, user, 1400, date(2026, 9, 20), category_id=EATING_OUT)
    items = list_transactions(conn, user_id=user.id)
    assert transactions.unusual_expenses(conn, Actor(user.id), items) == {}
    for day, cents in zip(range(22, 30), (800, 900, 1000, 1000, 1100, 1200, 1300, 1500)):
        add_expense(conn, clock, user, cents, date(2026, 6, day), category_id=EATING_OUT)  # within 90 days
    items = list_transactions(conn, user_id=user.id)
    flagged = transactions.unusual_expenses(conn, Actor(user.id), items)
    assert items[0].amount_cents == 1400 and flagged[items[0].id] == 1000
