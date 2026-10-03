"""Alert evaluation: gather the facts across domains, apply the pure rules, store the result (FR-32, §4.9).

Evaluation runs when the dashboard or alert centre loads and after each successful form post, in its
own transaction after the change has committed.
"""

import json
import sqlite3
from datetime import timedelta

from app.application.budgets import budgets
from app.application.context import Actor
from app.application.dashboard import forecast
from app.application.households import display_names
from app.application.transactions import unusual_expenses
from app.db.unit_of_work import transaction
from app.households import api as households
from app.insights import api as insights
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock

EXPENSE_EVENTS = (("shared_expense", "create"), ("shared_expense", "update"), ("household_bill_occurrence", "pay"))


def _bill_facts(conn: sqlite3.Connection, user_id: int, view) -> list[insights.BillFact]:
    facts = [insights.BillFact("personal", o.id, o.name, o.due_date, o.amount_cents, "/bills")
             for o in planning.open_occurrences_due_before(conn, user_id=user_id, before=view.cycle.horizon_end)]
    for household, active in households.user_households(conn, user_id=user_id):
        if not active or household.archived:
            continue
        series = {s.id: s for s in households.list_bill_series(conn, household_id=household.id)}
        for o in households.list_bill_occurrences(conn, household_id=household.id,
                                                  end_exclusive=view.cycle.horizon_end):
            share = households.share_of(series[o.series_id], o, user_id)
            if o.shared_expense_id is None and not o.skipped and share:
                facts.append(insights.BillFact("household", o.id, f"{o.name} ({household.name})", o.due_date, share,
                                               f"/households/{household.id}?tab=bills"))
    return facts


def _household_expense_facts(conn: sqlite3.Connection, user_id: int,
                             cursor: int) -> tuple[list[insights.HouseholdExpenseFact], int]:
    active = [h.id for h, is_active in households.user_households(conn, user_id=user_id) if is_active]
    if not active:
        return [], cursor
    rows = conn.execute(
        f"SELECT id, actor_user_id, household_id, entity_type, action, after_json FROM audit_events"
        f" WHERE id > ? AND household_id IN ({','.join('?' * len(active))}) ORDER BY id",
        (cursor, *active),
    ).fetchall()
    facts, last = [], cursor
    for row in rows:
        last = row["id"]
        if (row["entity_type"], row["action"]) not in EXPENSE_EVENTS or row["actor_user_id"] == user_id:
            continue
        after = json.loads(row["after_json"] or "{}")
        share = int(after.get("shares", {}).get(str(user_id), 0))
        if share > 0:
            name = display_names(conn, [row["actor_user_id"]])[row["actor_user_id"]]
            facts.append(insights.HouseholdExpenseFact(row["id"], row["household_id"], name,
                                                       after.get("description", "an expense"), share))
    return facts, last


def _settlement_facts(conn: sqlite3.Connection, user_id: int) -> list[insights.SettlementFact]:
    facts = []
    for s in households.awaiting(conn, user_id=user_id):
        other = s.initiated_by
        verb = "paid you" if s.payer_user_id == other else "received from you"
        facts.append(insights.SettlementFact(s.id, s.household_id, display_names(conn, [other])[other],
                                             s.amount_cents, verb))
    return facts


def evaluate(conn: sqlite3.Connection, user_id: int, clock: Clock) -> None:
    """Recompute this user's alerts. Idempotent: running it twice without changes adds nothing."""
    actor = Actor(user_id)
    result = forecast(conn, user_id, clock)
    view = result.dashboard
    cycle, today = view.cycle, view.cycle.today
    _, budget_rows = budgets(conn, actor, clock)
    recent = [t for t in ledger.list_transactions(conn, user_id=user_id, limit=200)
              if t.occurred_on > today - timedelta(days=7)]
    names = {c.id: c.name for c in ledger.list_categories(conn)}
    by_id = {t.id: t for t in recent}
    unusual = [insights.UnusualFact(tid, by_id[tid].amount_cents, typical, names.get(by_id[tid].category_id, ""),
                                    by_id[tid].occurred_on)
               for tid, typical in unusual_expenses(conn, actor, recent).items()]
    overdue = [insights.GoalFact(goal.id, goal.name)
               for goal, plan in planning.plans(conn, user_id=user_id, cycle=cycle) if plan.status == "overdue"]
    with transaction(conn):
        cursor = insights.get_cursor(conn, user_id=user_id)
        expense_facts, last = _household_expense_facts(conn, user_id, cursor)
        facts = insights.AlertFacts(
            today=today, cycle_start=cycle.start,
            bills=tuple(_bill_facts(conn, user_id, view)),
            budgets=tuple(insights.BudgetFact(row.category.id, row.category.name, row.state, row.consumption_cents,
                                              row.limit_cents) for row in budget_rows),
            pace_at_risk=result.forecast.status == "at_risk",
            unusual=tuple(unusual),
            settlements=tuple(_settlement_facts(conn, user_id)),
            household_expenses=tuple(expense_facts),
            allowance_missing=view.allowance_reminder,
            overdue_goals=tuple(overdue),
        )
        insights.sync_alerts(conn, user_id=user_id, specs=insights.desired_alerts(facts), now=clock.now_utc())
        insights.set_cursor(conn, user_id=user_id, last_audit_event_id=last)


def list_alerts(conn: sqlite3.Connection, actor: Actor) -> list[insights.Alert]:
    return insights.list_alerts(conn, user_id=actor.user_id)


def open_types(conn: sqlite3.Connection, actor: Actor) -> set[str]:
    return {alert.type for alert in list_alerts(conn, actor)}


def mark_read(conn: sqlite3.Connection, actor: Actor, alert_id: int, clock: Clock) -> None:
    with transaction(conn):
        insights.mark_read(conn, user_id=actor.user_id, alert_id=alert_id, now=clock.now_utc())


def dismiss(conn: sqlite3.Connection, actor: Actor, alert_id: int, clock: Clock) -> None:
    with transaction(conn):
        insights.dismiss(conn, user_id=actor.user_id, alert_id=alert_id, now=clock.now_utc())
