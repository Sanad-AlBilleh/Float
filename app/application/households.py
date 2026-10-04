"""Household membership use cases: each authorizes, runs in one transaction, and audits with the household's ID
(FR-17–19, FR-33)."""

import sqlite3
from dataclasses import asdict, dataclass, field

from app.application import audit
from app.application.authz import require_member, require_owner, require_viewer
from app.application.context import Actor
from app.application.setup import is_setup_complete
from app.db.unit_of_work import transaction
from app.households import api as households
from app.identity import api as identity
from app.shared.clock import Clock
from app.shared.errors import ConflictError


@dataclass(frozen=True)
class MemberView:
    user_id: int
    display_name: str
    role: str
    status: str
    net_cents: int | None  # None when the viewer has left: current balances are for current members only


def _audit(conn, actor: Actor, household_id: int, entity_type: str, entity_id: int | None, action: str,
           clock: Clock, before=None, after=None) -> None:
    audit.record(conn, actor_user_id=actor.user_id, household_id=household_id, entity_type=entity_type,
                 entity_id=entity_id, action=action, now=clock.now_utc(), before=before, after=after,
                 request_id=actor.request_id)


def display_names(conn: sqlite3.Connection, user_ids) -> dict[int, str]:
    return {user_id: identity.get_user(conn, user_id).display_name for user_id in set(user_ids)}


def my_households(conn: sqlite3.Connection, actor: Actor) -> list[tuple[households.Household, bool]]:
    return households.user_households(conn, user_id=actor.user_id)


def member_views(conn: sqlite3.Connection, household_id: int, *, with_balances: bool = True) -> list[MemberView]:
    nets = households.balances(conn, household_id=household_id)
    people = households.members(conn, household_id=household_id)
    names = display_names(conn, [m.user_id for m in people])
    return [MemberView(m.user_id, names[m.user_id], m.role, m.status, nets.get(m.user_id, 0) if with_balances else None)
            for m in people]


def create_household(conn: sqlite3.Connection, actor: Actor, name: str, clock: Clock) -> households.Household:
    with transaction(conn):
        created = households.create_household(conn, owner_id=actor.user_id, name=name, now=clock.now_utc())
        _audit(conn, actor, created.id, "household", created.id, "create", clock, after=asdict(created))
    return created


def join_household(conn: sqlite3.Connection, actor: Actor, code: str, clock: Clock) -> households.Household:
    if not is_setup_complete(conn, actor.user_id):
        raise ConflictError("Complete setup first.")
    with transaction(conn):
        joined = households.join(conn, user_id=actor.user_id, code=code, now=clock.now_utc())
        _audit(conn, actor, joined.id, "membership", actor.user_id, "join", clock)
    return joined


def invite(conn: sqlite3.Connection, actor: Actor, household_id: int, clock: Clock) -> str:
    """Return a new invitation code. The audit event records that a code was made, never the code."""
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        code = households.create_invitation(conn, household_id=household_id, created_by=actor.user_id,
                                            now=clock.now_utc())
        _audit(conn, actor, household_id, "invitation", None, "create", clock)
    return code


def invitations(conn: sqlite3.Connection, actor: Actor, household_id: int, clock: Clock) -> list[households.Invitation]:
    require_owner(conn, actor.user_id, household_id)
    return households.list_invitations(conn, household_id=household_id, now=clock.now_utc())


def revoke(conn: sqlite3.Connection, actor: Actor, household_id: int, invitation_id: int, clock: Clock) -> None:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        households.revoke_invitation(conn, household_id=household_id, invitation_id=invitation_id,
                                     now=clock.now_utc())
        _audit(conn, actor, household_id, "invitation", invitation_id, "revoke", clock)


def leave(conn: sqlite3.Connection, actor: Actor, household_id: int, clock: Clock) -> None:
    with transaction(conn):
        require_member(conn, actor.user_id, household_id)
        households.leave(conn, household_id=household_id, user_id=actor.user_id, now=clock.now_utc())
        _audit(conn, actor, household_id, "membership", actor.user_id, "leave", clock)


def remove(conn: sqlite3.Connection, actor: Actor, household_id: int, user_id: int, clock: Clock) -> None:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        households.remove_member(conn, household_id=household_id, user_id=user_id, now=clock.now_utc())
        _audit(conn, actor, household_id, "membership", user_id, "remove", clock)


def transfer(conn: sqlite3.Connection, actor: Actor, household_id: int, version: int, new_owner_id: int,
             clock: Clock) -> None:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        before = households.get_household(conn, household_id=household_id)
        after = households.transfer_ownership(conn, household_id=household_id, version=version,
                                              new_owner_id=new_owner_id)
        _audit(conn, actor, household_id, "household", household_id, "transfer_ownership", clock,
               asdict(before), asdict(after))


def rename(conn: sqlite3.Connection, actor: Actor, household_id: int, version: int, name: str, clock: Clock) -> None:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        before = households.get_household(conn, household_id=household_id)
        after = households.rename(conn, household_id=household_id, version=version, name=name)
        _audit(conn, actor, household_id, "household", household_id, "rename", clock, asdict(before), asdict(after))


def archive(conn: sqlite3.Connection, actor: Actor, household_id: int, version: int, clock: Clock) -> None:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        before = households.get_household(conn, household_id=household_id)
        after = households.archive(conn, household_id=household_id, version=version, now=clock.now_utc())
        _audit(conn, actor, household_id, "household", household_id, "archive", clock, asdict(before), asdict(after))


def viewer(conn: sqlite3.Connection, actor: Actor, household_id: int) -> households.Member:
    return require_viewer(conn, actor.user_id, household_id)


@dataclass(frozen=True)
class HouseholdPage:
    household: households.Household
    me: households.Member
    members: list[MemberView]
    invitations: list[households.Invitation]
    expenses: list[households.SharedExpense] = field(default_factory=list)
    bill_expense_ids: frozenset[int] = frozenset()
    plan: list[households.Transfer] = field(default_factory=list)
    settlements: list[households.Settlement] = field(default_factory=list)

    @property
    def my_net_cents(self) -> int:
        return next((m.net_cents or 0 for m in self.members if m.user_id == self.me.user_id), 0)

    @property
    def current(self) -> bool:
        """Only current members see the household as it is now (review finding 6)."""
        return self.me.status == "active"

    @property
    def is_owner(self) -> bool:
        return self.me.status == "active" and self.me.role == "owner" and not self.household.archived

    @property
    def can_write(self) -> bool:
        return self.me.status == "active" and not self.household.archived

    @property
    def active_members(self) -> list[MemberView]:
        return [m for m in self.members if m.status == "active"]

    def name_of(self, user_id: int) -> str:
        return next((m.display_name for m in self.members if m.user_id == user_id), "A former member")


def page(conn: sqlite3.Connection, actor: Actor, household_id: int, clock: Clock) -> HouseholdPage:
    me = require_viewer(conn, actor.user_id, household_id)
    household = households.get_household(conn, household_id=household_id)
    owner = me.status == "active" and me.role == "owner" and not household.archived
    return HouseholdPage(
        household=household,
        me=me,
        members=member_views(conn, household_id, with_balances=me.status == "active"),
        invitations=households.list_invitations(conn, household_id=household_id, now=clock.now_utc()) if owner else [],
        expenses=_visible(me, households.list_expenses(conn, household_id=household_id)),
        plan=households.simplify(households.balances(conn, household_id=household_id)) if me.status == "active" else [],
        settlements=[s for s in households.list_settlements(conn, household_id=household_id)
                     if me.status == "active" or me.joined_on <= s.paid_on <= me.ended_at.date()],
    )


def _visible(me: households.Member, expenses: list[households.SharedExpense]) -> list[households.SharedExpense]:
    """Former members see the expenses from their membership period only (FR-19)."""
    if me.status == "active":
        return expenses
    return [e for e in expenses if me.joined_on <= e.spent_on <= me.ended_at.date()]


def member(conn: sqlite3.Connection, actor: Actor, household_id: int) -> households.Member:
    """404 unless the actor is an active member: used before parsing any household form."""
    return require_member(conn, actor.user_id, household_id)


def owner(conn: sqlite3.Connection, actor: Actor, household_id: int) -> households.Member:
    return require_owner(conn, actor.user_id, household_id)
