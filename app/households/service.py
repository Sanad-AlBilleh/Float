"""Households, invitations, and membership on an open connection (FR-17–19).

Authorization (who may call what) is the application layer's job; these functions enforce the
household's own rules: limits, single-use codes, and what blocks someone from leaving.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.households import repository
from app.households.rules import (
    INVALID_CODE,
    INVITE_TTL,
    MAX_HOUSEHOLDS,
    MAX_MEMBERS,
    compute_nets,
    hash_code,
    new_invite_code,
    normalize_code,
    validate_household_name,
)
from app.shared.clock import from_utc_text
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.money import format_money

SQLITE_MAX_ID = 2**63 - 1
STALE_MESSAGE = "This household changed since you opened it. Reload the page and try again."
ARCHIVED_MESSAGE = "This household is archived, so it is read-only."


@dataclass(frozen=True)
class Household:
    id: int
    name: str
    owner_user_id: int
    archived: bool
    version: int


@dataclass(frozen=True)
class Member:
    user_id: int
    role: str  # "owner" or "member"
    status: str  # "active", "left", or "removed"
    joined_at: datetime
    ended_at: datetime | None

    @property
    def joined_on(self) -> date:
        return self.joined_at.date()


@dataclass(frozen=True)
class Invitation:
    id: int
    created_by: int
    created_at: datetime
    expires_at: datetime


def _household(row: sqlite3.Row) -> Household:
    return Household(row["id"], row["name"], row["owner_user_id"], row["archived_at"] is not None, row["version"])


def _member(row: sqlite3.Row) -> Member:
    return Member(row["user_id"], row["role"], row["status"], from_utc_text(row["joined_at"]),
                  None if row["ended_at"] is None else from_utc_text(row["ended_at"]))


def get_household(conn: sqlite3.Connection, *, household_id: int) -> Household:
    row = repository.get_household(conn, household_id) if 1 <= household_id <= SQLITE_MAX_ID else None
    if row is None:
        raise NotFoundError("No such household.")
    return _household(row)


def require_open(conn: sqlite3.Connection, *, household_id: int) -> Household:
    household = get_household(conn, household_id=household_id)
    if household.archived:
        raise ConflictError(ARCHIVED_MESSAGE)
    return household


def _check_household_limit(conn: sqlite3.Connection, user_id: int) -> None:
    if repository.count_active_households(conn, user_id=user_id) >= MAX_HOUSEHOLDS:
        raise ValidationError.single("code", "You already belong to three households, the most Float allows.")


def create_household(conn: sqlite3.Connection, *, owner_id: int, name: str, now: datetime) -> Household:
    validate_household_name(name)
    try:
        _check_household_limit(conn, owner_id)
    except ValidationError as error:
        raise ValidationError.single("name", error.errors["code"]) from None
    household_id = repository.insert_household(conn, name=name, owner_id=owner_id, now=now)
    repository.insert_membership(conn, household_id=household_id, user_id=owner_id, role="owner", now=now)
    return get_household(conn, household_id=household_id)


def rename(conn: sqlite3.Connection, *, household_id: int, version: int, name: str) -> Household:
    require_open(conn, household_id=household_id)
    validate_household_name(name)
    if repository.rename(conn, household_id=household_id, version=version, name=name) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_household(conn, household_id=household_id)


def membership(conn: sqlite3.Connection, *, household_id: int, user_id: int) -> Member | None:
    """The user's current membership: active, or the most recent one that ended. None if never a member."""
    row = repository.latest_membership(conn, household_id=household_id, user_id=user_id)
    return None if row is None else _member(row)


def members(conn: sqlite3.Connection, *, household_id: int) -> list[Member]:
    """Each person who has been a member, once, with their current or latest membership."""
    seen: dict[int, Member] = {}
    for row in repository.memberships(conn, household_id=household_id):
        seen.setdefault(row["user_id"], _member(row))
    return list(seen.values())


def active_member_ids(conn: sqlite3.Connection, *, household_id: int) -> list[int]:
    return sorted(m.user_id for m in members(conn, household_id=household_id) if m.status == "active")


def user_households(conn: sqlite3.Connection, *, user_id: int) -> list[tuple[Household, bool]]:
    """Every household the user has belonged to, with whether they are an active member now."""
    return [(get_household(conn, household_id=row["household_id"]), bool(row["active"]))
            for row in repository.user_household_ids(conn, user_id=user_id)]


def transfer_ownership(conn: sqlite3.Connection, *, household_id: int, version: int,
                       new_owner_id: int) -> Household:
    household = require_open(conn, household_id=household_id)
    if new_owner_id == household.owner_user_id or repository.active_membership(
            conn, household_id=household_id, user_id=new_owner_id) is None:
        raise ValidationError.single("new_owner", "Choose another active member.")
    if repository.set_owner(conn, household_id=household_id, version=version, owner_id=new_owner_id) != 1:
        raise ConflictError(STALE_MESSAGE)
    repository.set_role(conn, household_id=household_id, user_id=household.owner_user_id, role="member")
    repository.set_role(conn, household_id=household_id, user_id=new_owner_id, role="owner")
    return get_household(conn, household_id=household_id)


def create_invitation(conn: sqlite3.Connection, *, household_id: int, created_by: int, now: datetime) -> str:
    """Store a new code's hash and return the plain code. It is shown once and never stored."""
    require_open(conn, household_id=household_id)
    code = new_invite_code()
    repository.insert_invitation(conn, household_id=household_id, code_hash=hash_code(code), created_by=created_by,
                                 now=now, expires_at=now + INVITE_TTL)
    return code


def list_invitations(conn: sqlite3.Connection, *, household_id: int, now: datetime) -> list[Invitation]:
    return [Invitation(row["id"], row["created_by"], from_utc_text(row["created_at"]), from_utc_text(row["expires_at"]))
            for row in repository.active_invitations(conn, household_id=household_id, now=now)]


def revoke_invitation(conn: sqlite3.Connection, *, household_id: int, invitation_id: int, now: datetime) -> None:
    if not 1 <= invitation_id <= SQLITE_MAX_ID or repository.revoke_invitation(
            conn, household_id=household_id, invitation_id=invitation_id, now=now) != 1:
        raise NotFoundError("No such invitation.")


def join(conn: sqlite3.Connection, *, user_id: int, code: str, now: datetime) -> Household:
    """FR-18: unknown, expired, used, and revoked codes all give the same message."""
    invitation = repository.invitation_by_hash(conn, hash_code(normalize_code(code)))
    if (invitation is None or invitation["used_by"] is not None or invitation["revoked_at"] is not None
            or from_utc_text(invitation["expires_at"]) <= now):
        raise ValidationError.single("code", INVALID_CODE)
    household = get_household(conn, household_id=invitation["household_id"])
    if household.archived:
        raise ValidationError.single("code", INVALID_CODE)
    if repository.active_membership(conn, household_id=household.id, user_id=user_id) is not None:
        raise ConflictError("You are already a member of this household.")
    if repository.count_active_members(conn, household_id=household.id) >= MAX_MEMBERS:
        raise ValidationError.single("code", "This household is full: it already has eight members.")
    _check_household_limit(conn, user_id)
    if repository.use_invitation(conn, invitation_id=invitation["id"], user_id=user_id, now=now) != 1:
        raise ValidationError.single("code", INVALID_CODE)
    repository.insert_membership(conn, household_id=household.id, user_id=user_id, role="member", now=now)
    return household


def balances(conn: sqlite3.Connection, *, household_id: int) -> dict[int, int]:
    """Each member's net balance (SRS §4.4): positive means the others owe them."""
    splits: dict[int, dict[int, int]] = {}
    for row in repository.expense_splits(conn, household_id=household_id):
        splits.setdefault(row["expense_id"], {})[row["user_id"]] = row["share_cents"]
    expenses = [(row["payer_user_id"], row["amount_cents"], splits.get(row["id"], {}))
                for row in repository.expense_totals(conn, household_id=household_id)]
    settlements = [(row["payer_user_id"], row["payee_user_id"], row["amount_cents"])
                   for row in repository.confirmed_settlements(conn, household_id=household_id)]
    return compute_nets([m.user_id for m in members(conn, household_id=household_id)], expenses, settlements)


def leave_blockers(conn: sqlite3.Connection, *, household_id: int, user_id: int) -> list[str]:
    """FR-19: every reason the member cannot leave or be removed yet, in plain words."""
    reasons = []
    net = balances(conn, household_id=household_id).get(user_id, 0)
    if net > 0:
        reasons.append(f"The others still owe you {format_money(net)}. Settle up first.")
    elif net < 0:
        reasons.append(f"You still owe {format_money(-net)}. Settle up first.")
    if repository.has_pending_settlement(conn, household_id=household_id, user_id=user_id):
        reasons.append("A settlement involving you is still pending.")
    for name in repository.active_bill_names(conn, household_id=household_id, user_id=user_id):
        reasons.append(f"You share the household bill “{name}”. The owner must end it first.")
    return reasons


def _end(conn: sqlite3.Connection, *, household_id: int, user_id: int, status: str, now: datetime) -> None:
    household = require_open(conn, household_id=household_id)
    if user_id == household.owner_user_id:
        raise ConflictError("The owner cannot leave. Transfer ownership to another member first, "
                            "or archive the household if you are the only one left.")
    if repository.active_membership(conn, household_id=household_id, user_id=user_id) is None:
        raise NotFoundError("No such member.")
    reasons = leave_blockers(conn, household_id=household_id, user_id=user_id)
    if reasons:
        raise ConflictError(" ".join(reasons))
    repository.end_membership(conn, household_id=household_id, user_id=user_id, status=status, now=now)


def leave(conn: sqlite3.Connection, *, household_id: int, user_id: int, now: datetime) -> None:
    _end(conn, household_id=household_id, user_id=user_id, status="left", now=now)


def remove_member(conn: sqlite3.Connection, *, household_id: int, user_id: int, now: datetime) -> None:
    _end(conn, household_id=household_id, user_id=user_id, status="removed", now=now)


def archive(conn: sqlite3.Connection, *, household_id: int, version: int, now: datetime) -> Household:
    """FR-17: only when every net is zero and nothing is pending; the household becomes read-only history."""
    require_open(conn, household_id=household_id)
    if any(balances(conn, household_id=household_id).values()):
        raise ConflictError("Everyone must be settled up (every balance at €0.00) before archiving.")
    if repository.has_pending_settlement(conn, household_id=household_id):
        raise ConflictError("Resolve the pending settlements before archiving.")
    if repository.archive(conn, household_id=household_id, version=version, now=now) != 1:
        raise ConflictError(STALE_MESSAGE)
    repository.end_all_memberships(conn, household_id=household_id, now=now)
    return get_household(conn, household_id=household_id)
