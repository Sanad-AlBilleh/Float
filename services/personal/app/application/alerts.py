"""Alert evaluation: gather the facts across domains, apply the pure rules, store the result (FR-32, §4.9).

Evaluation runs when the dashboard or alert centre loads and after each successful form post, in its
own transaction after the change has committed.
"""

import logging
from datetime import timedelta

from app.application.budgets import budgets
from app.application.context import Actor
from app.application.dashboard import forecast
from app.application.people import display_names
from app.application.setup import current_settings
from app.application.transactions import unusual_expenses
from app.clients.households import (
    EMPTY_POSITION,
    Events,
    HouseholdsClient,
    HouseholdsUnavailable,
)
from app.db.connection import Connection
from app.db.unit_of_work import transaction
from app.insights import api as insights
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import cycle_for

logger = logging.getLogger("float.alerts")


def _bill_facts(conn: Connection, user_id: int, view) -> list[insights.BillFact]:
    facts = [insights.BillFact("personal", o.id, o.name, o.due_date, o.amount_cents, "/bills")
             for o in planning.open_occurrences_due_before(conn, user_id=user_id, before=view.cycle.horizon_end)]
    facts += [insights.BillFact("household", b.occurrence_id, b.name, b.due_date, b.share_cents,
                                f"/household.html?id={b.household_id}&tab=bills")
              for b in view.household_open_bills]
    return facts


def evaluate(conn: Connection, user_id: int, clock: Clock, households: HouseholdsClient | None = None) -> None:
    """Recompute this user's alerts. Idempotent: running it twice without changes adds nothing.

    Household facts come from the households service in three calls. If it does not answer, nothing is
    changed: stored alerts stay as they were, instead of household alerts being "resolved" only because
    their facts could not be read (ADR-6).
    """
    actor = Actor(user_id)
    ledger_settings, planning_settings = current_settings(conn, user_id)
    cycle = cycle_for(clock.today(), planning_settings.allowance_day)
    window_start = cycle.today - timedelta(days=insights.pace_window_days(cycle.today, ledger_settings.tracking_start))
    cursor = insights.get_cursor(conn, user_id=user_id)
    try:
        if households is None:  # no households service configured: nothing household-related to alert on
            position, shares, events = EMPTY_POSITION, [], Events(cursor, (), ())
        else:
            position = households.position(user_id, window_end=cycle.next_allowance, horizon_end=cycle.horizon_end)
            shares = households.shares(user_id, start=min(cycle.start, window_start),
                                       end_exclusive=cycle.next_allowance)
            events = households.events(user_id, after=cursor)
    except HouseholdsUnavailable:
        logger.warning("alerts for user %s not re-evaluated: households service unavailable", user_id)
        return
    result = forecast(conn, user_id, clock, households, position, _in(shares, window_start, cycle.today))
    view = result.dashboard
    today = view.cycle.today
    _, budget_rows = budgets(conn, actor, clock, shares=_in(shares, cycle.start, cycle.next_allowance))
    recent = [t for t in ledger.list_transactions(conn, user_id=user_id, limit=200)
              if t.occurred_on > today - timedelta(days=7)]
    names = ledger.category_names(conn)
    by_id = {t.id: t for t in recent}
    unusual = [insights.UnusualFact(tid, by_id[tid].amount_cents, typical, names.get(by_id[tid].category_id, ""),
                                    by_id[tid].occurred_on)
               for tid, typical in unusual_expenses(conn, actor, recent).items()]
    overdue = [insights.GoalFact(goal.id, goal.name)
               for goal, plan in planning.plans(conn, user_id=user_id, cycle=cycle) if plan.status == "overdue"]
    people = display_names(conn, [e.actor_user_id for e in events.expenses]
                           + [s.other_user_id for s in events.settlements])
    expense_facts = [insights.HouseholdExpenseFact(e.audit_event_id, e.household_id, people[e.actor_user_id],
                                                   e.description, e.share_cents)
                     for e in events.expenses if e.actor_user_id != user_id and e.share_cents > 0]
    settlement_facts = [insights.SettlementFact(s.settlement_id, s.household_id, people[s.other_user_id],
                                                s.amount_cents, s.verb) for s in events.settlements]
    with transaction(conn):
        facts = insights.AlertFacts(
            today=today, cycle_start=cycle.start,
            bills=tuple(_bill_facts(conn, user_id, view)),
            budgets=tuple(insights.BudgetFact(row.category.id, row.category.name, row.state, row.consumption_cents,
                                              row.limit_cents) for row in budget_rows),
            pace_at_risk=result.forecast.status == "at_risk",
            unusual=tuple(unusual),
            settlements=tuple(settlement_facts),
            household_expenses=tuple(expense_facts),
            allowance_missing=view.allowance_reminder,
            overdue_goals=tuple(overdue),
        )
        insights.sync_alerts(conn, user_id=user_id, specs=insights.desired_alerts(facts), now=clock.now_utc())
        insights.set_cursor(conn, user_id=user_id, last_audit_event_id=max(cursor, events.last_id))


def _in(shares, start, end_exclusive) -> list[insights.ShareRow]:
    """The shares dated in [start, end_exclusive), as Insights expects them."""
    return [insights.ShareRow(s.amount_cents, s.occurred_on, s.category_id, s.from_household_bill, s.one_off)
            for s in shares if start <= s.occurred_on < end_exclusive]


def list_alerts(conn: Connection, actor: Actor) -> list[insights.Alert]:
    return insights.list_alerts(conn, user_id=actor.user_id)


def open_types(conn: Connection, actor: Actor) -> set[str]:
    return {alert.type for alert in list_alerts(conn, actor)}


def mark_read(conn: Connection, actor: Actor, alert_id: int, clock: Clock) -> None:
    with transaction(conn):
        insights.mark_read(conn, user_id=actor.user_id, alert_id=alert_id, now=clock.now_utc())


def dismiss(conn: Connection, actor: Actor, alert_id: int, clock: Clock) -> None:
    with transaction(conn):
        insights.dismiss(conn, user_id=actor.user_id, alert_id=alert_id, now=clock.now_utc())
