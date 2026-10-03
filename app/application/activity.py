"""Activity feeds from the audit trail (FR-33): a household's events for its members, and a user's own
personal events for that user."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.application.authz import require_viewer
from app.application.context import Actor
from app.application.households import display_names
from app.shared.clock import from_utc_text, to_utc_text
from app.shared.money import format_money

LIMIT = 100


@dataclass(frozen=True)
class ActivityItem:
    when: datetime
    text: str


def _money(data: dict, key: str = "amount_cents") -> str:
    return format_money(int(data.get(key, 0)))


def _describe(entity: str, action: str, before: dict, after: dict, names: dict[int, str]) -> str:
    data = after or before
    quoted = f"“{data.get('description') or data.get('name') or ''}”"
    verbs = {"create": "added", "update": "changed", "delete": "deleted"}
    if entity == "household":
        return {"create": "created the household", "rename": f"renamed the household to “{after.get('name')}”",
                "transfer_ownership": f"handed ownership to {names.get(after.get('owner_user_id'), 'a member')}",
                "archive": "archived the household"}.get(action, f"changed the household ({action})")
    if entity == "membership":
        return {"join": "joined the household", "leave": "left the household",
                "remove": "removed a member"}.get(action, action)
    if entity == "invitation":
        return "created an invitation code" if action == "create" else "revoked an invitation code"
    if entity == "shared_expense":
        return f"{verbs.get(action, action)} the shared expense {quoted} ({_money(data)})"
    if entity == "settlement":
        transfer = (f"{names.get(data.get('payer_user_id'), 'someone')} paid "
                    f"{names.get(data.get('payee_user_id'), 'someone')} {_money(data)}")
        return {"create": f"recorded a transfer: {transfer}", "confirm": f"confirmed the transfer: {transfer}",
                "reject": f"rejected the transfer: {transfer}", "cancel": f"cancelled the transfer: {transfer}"}.get(
            action, action)
    if entity == "household_bill":
        return f"added the household bill {quoted}" if action == "create" else "ended a household bill"
    if entity == "household_bill_occurrence":
        return {"pay": f"paid the household bill {quoted} ({_money(data)})", "undo_payment": "undid a bill payment",
                "update": "changed a household bill's amount or date", "skip": "skipped a household bill",
                "unskip": "unskipped a household bill"}.get(action, action)
    if entity == "transaction":
        kind = "income" if data.get("kind") == "income" else "an expense"
        return f"{verbs.get(action, action)} {kind} of {_money(data)}"
    if entity == "bill_series":
        return {"create": f"added the bill {quoted}", "end": f"ended the bill {quoted}",
                "split": f"changed the bill {quoted} from a date on", "update": f"changed the bill {quoted}"}.get(
            action, action)
    if entity == "bill_occurrence":
        return {"pay": "paid a bill", "undo_payment": "undid a bill payment", "skip": "skipped a bill",
                "unskip": "unskipped a bill", "update": "changed one bill's amount or date"}.get(action, action)
    if entity == "savings_goal":
        return {"create": f"created the goal {quoted}", "update": f"changed the goal {quoted}",
                "protect": f"protected money for {quoted}", "release": f"released money from {quoted}",
                "archive": f"archived the goal {quoted}"}.get(action, action)
    if entity == "budget":
        return "set a budget limit" if action == "set" else "removed a budget limit"
    if entity == "setup":
        return "completed setup"
    if entity == "planning_settings":
        return "changed the planned allowance"
    return f"{entity.replace('_', ' ')}: {action}"


def _items(conn: sqlite3.Connection, rows: list[sqlite3.Row], *, personal: bool) -> list[ActivityItem]:
    names = display_names(conn, [row["actor_user_id"] for row in rows if row["actor_user_id"]])
    items = []
    for row in rows:
        before = json.loads(row["before_json"] or "{}")
        after = json.loads(row["after_json"] or "{}")
        for data in (before, after):
            for key in ("payer_user_id", "payee_user_id", "owner_user_id"):
                if isinstance(data.get(key), int) and data[key] not in names:
                    names.update(display_names(conn, [data[key]]))
        who = "You" if personal else names.get(row["actor_user_id"], "Someone")
        items.append(ActivityItem(from_utc_text(row["occurred_at"]),
                                  f"{who} {_describe(row['entity_type'], row['action'], before, after, names)}"))
    return items


def household_activity(conn: sqlite3.Connection, actor: Actor, household_id: int) -> list[ActivityItem]:
    """Members see every event; former members only those from their membership period (FR-19, FR-33)."""
    me = require_viewer(conn, actor.user_id, household_id)
    query = ("SELECT actor_user_id, entity_type, action, before_json, after_json, occurred_at FROM audit_events"
             " WHERE household_id = ?")
    args: list = [household_id]
    if me.status != "active":
        query += " AND occurred_at BETWEEN ? AND ?"
        args += [to_utc_text(me.joined_at), to_utc_text(me.ended_at)]
    rows = conn.execute(query + " ORDER BY id DESC LIMIT ?", (*args, LIMIT)).fetchall()
    return _items(conn, rows, personal=False)


def personal_activity(conn: sqlite3.Connection, actor: Actor) -> list[ActivityItem]:
    rows = conn.execute(
        "SELECT actor_user_id, entity_type, action, before_json, after_json, occurred_at FROM audit_events"
        " WHERE actor_user_id = ? AND household_id IS NULL ORDER BY id DESC LIMIT ?", (actor.user_id, LIMIT),
    ).fetchall()
    return _items(conn, rows, personal=True)
