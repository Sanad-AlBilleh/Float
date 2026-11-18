"""Alert evaluation, deduplication, resolution, and dismissal (FR-32, AT-24)."""

from datetime import date

from app.application import alerts, bills
from app.application.context import Actor
from app.clients.households import AwaitingSettlement, ExpenseEvent
from app.insights.api import alert_row_count, get_cursor
from tests.scenarios.flat_3b import build_flat_3b


def types(conn, actor, clock, households=None):
    alerts.evaluate(conn, actor.user_id, clock, households)
    return alerts.open_types(conn, actor)


def test_evaluating_twice_creates_nothing_new(conn):
    flat = build_flat_3b(conn)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    rows = alert_row_count(conn, user_id=flat.ana.user_id)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    assert alert_row_count(conn, user_id=flat.ana.user_id) == rows > 0


def test_paying_a_bill_resolves_its_alert(conn):
    flat = build_flat_3b(conn)
    flat.clock.advance(days=3)  # 23 September: Phone + gym is due in two days
    assert "BILL_DUE_SOON" in types(conn, flat.ana, flat.clock, flat.households)
    phone = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.pay_occurrence(conn, flat.ana, phone.id, phone.version, date(2026, 9, 23), flat.clock)
    assert "BILL_DUE_SOON" not in types(conn, flat.ana, flat.clock, flat.households)


def test_a_dismissed_alert_stays_dismissed_when_its_condition_returns(conn):
    flat = build_flat_3b(conn)
    flat.clock.advance(days=3)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    [due] = [a for a in alerts.list_alerts(conn, flat.ana) if a.type == "BILL_DUE_SOON" and "Phone" in a.message]
    alerts.dismiss(conn, flat.ana, due.id, flat.clock)
    phone = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.skip_occurrence(conn, flat.ana, phone.id, phone.version, flat.clock)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    skipped = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.unskip_occurrence(conn, flat.ana, skipped.id, skipped.version, flat.clock)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    assert not [a for a in alerts.list_alerts(conn, flat.ana) if "Phone" in a.message]


def test_household_expenses_reach_participants_but_not_the_actor(conn):
    flat = build_flat_3b(conn)
    households = flat.households
    for actor in (flat.ana, flat.ben, flat.carla):
        alerts.evaluate(conn, actor.user_id, flat.clock, households)
    # The households service reports Ben's "Pizza" (€40, split Ana/Ben) as audit event 7 to Ana only:
    # it leaves out the actor and members with no share.
    households.expense_events.append((flat.ana.user_id, ExpenseEvent(7, flat.household_id, flat.ben.user_id,
                                                                      "Pizza", 2000)))

    def pizza_alerts(actor):
        alerts.evaluate(conn, actor.user_id, flat.clock, households)
        return [a for a in alerts.list_alerts(conn, actor) if "Pizza" in a.message]
    assert pizza_alerts(flat.ben) == []
    assert pizza_alerts(flat.carla) == []
    [pizza] = pizza_alerts(flat.ana)
    assert "Ben" in pizza.message and "€20.00" in pizza.message
    assert get_cursor(conn, user_id=flat.ana.user_id) == 7
    assert pizza.type == "HOUSEHOLD_EXPENSE_ADDED"
    assert len(pizza_alerts(flat.ana)) == 1  # the event is not reported twice


def test_the_other_rules_fire_on_their_conditions(conn):
    flat = build_flat_3b(conn)
    households = flat.households
    households.awaiting[flat.ben.user_id] = [AwaitingSettlement(1, flat.household_id, flat.ana.user_id, 1000,
                                                                "paid you")]
    assert "SETTLEMENT_AWAITING_YOU" in types(conn, flat.ben, flat.clock, households)
    assert "SETTLEMENT_AWAITING_YOU" not in types(conn, flat.ana, flat.clock, households)
    households.awaiting.clear()  # Ben confirmed it in the households service
    assert "SETTLEMENT_AWAITING_YOU" not in types(conn, flat.ben, flat.clock, households)
    flat.clock.advance(days=12)  # 2 October: a new cycle, with no allowance recorded yet
    assert {"ALLOWANCE_NOT_RECORDED", "BILL_OVERDUE"} <= types(conn, flat.ana, flat.clock, households)


def test_household_bills_due_soon_come_from_the_households_service(conn):
    flat = build_flat_3b(conn)
    flat.clock.advance(days=6)  # 26 September: the flat's Internet is due in two days
    found = [a for a in (alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
                         or alerts.list_alerts(conn, flat.ana)) if "Internet" in a.message]
    assert [a.type for a in found] == ["BILL_DUE_SOON"]


def test_alerts_are_left_alone_while_the_households_service_is_down(conn):
    flat = build_flat_3b(conn)
    flat.households.awaiting[flat.ben.user_id] = [AwaitingSettlement(1, flat.household_id, flat.ana.user_id,
                                                                     1000, "paid you")]
    assert "SETTLEMENT_AWAITING_YOU" in types(conn, flat.ben, flat.clock, flat.households)
    flat.households.down = True
    flat.households.awaiting.clear()
    # Not "resolved" just because the facts could not be read: the stored alerts stay as they were.
    assert "SETTLEMENT_AWAITING_YOU" in types(conn, flat.ben, flat.clock, flat.households)


def test_pace_budget_unusual_and_goal_alerts(conn, clock):
    from app.application import budgets, goals
    from tests.factories import add_expense, complete_setup, make_user

    user = make_user(conn, clock, "dina")
    complete_setup(conn, clock, user, tracking_start=date(2026, 9, 1), opening_cents=10000)
    dina = Actor(user.id)
    for day, cents in zip(range(2, 10), (800, 900, 1000, 1000, 1100, 1200, 1300, 1500)):
        add_expense(conn, clock, user, cents, date(2026, 9, day), category_id=2)
    add_expense(conn, clock, user, 3000, date(2026, 9, 29), category_id=2)
    budgets.set_limit(conn, dina, 2, 5000, "template", clock)
    goals.add_goal(conn, dina, goals.GoalInput("Old plan", 5000, date(2026, 9, 1), 2, True), clock)
    found = types(conn, dina, clock)
    assert {"PACE_AT_RISK", "BUDGET_OVER", "UNUSUAL_EXPENSE", "GOAL_OVERDUE"} <= found


def test_a_resolved_alert_reopens_when_its_condition_returns(conn):
    flat = build_flat_3b(conn)
    flat.clock.advance(days=3)
    assert "BILL_DUE_SOON" in types(conn, flat.ana, flat.clock, flat.households)
    phone = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.skip_occurrence(conn, flat.ana, phone.id, phone.version, flat.clock)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    assert not [a for a in alerts.list_alerts(conn, flat.ana) if "Phone" in a.message]
    skipped = bills.get_occurrence(conn, flat.ana, flat.phone_occurrence_id)
    bills.unskip_occurrence(conn, flat.ana, skipped.id, skipped.version, flat.clock)
    alerts.evaluate(conn, flat.ana.user_id, flat.clock, flat.households)
    assert [a.type for a in alerts.list_alerts(conn, flat.ana) if "Phone" in a.message] == ["BILL_DUE_SOON"]
