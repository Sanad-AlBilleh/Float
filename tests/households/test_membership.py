"""Households, invitations, and membership rules (FR-17–19, AT-13)."""

from datetime import date, timedelta

import pytest

from app.households.api import (
    INVALID_CODE,
    archive,
    create_household,
    create_invitation,
    get_household,
    join,
    leave,
    list_invitations,
    leave_blockers,
    members,
    remove_member,
    rename,
    revoke_invitation,
    transfer_ownership,
    user_households,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from tests.factories import make_user


@pytest.fixture
def people(conn, clock):
    return [make_user(conn, clock, name) for name in ("ana", "ben", "carla", "dina")]


@pytest.fixture
def flat(conn, clock, people):
    return create_household(conn, owner_id=people[0].id, name="Flat 3B", now=clock.now_utc())


def invite_and_join(conn, clock, household, user):
    code = create_invitation(conn, household_id=household.id, created_by=household.owner_user_id,
                             now=clock.now_utc())
    return join(conn, user_id=user.id, code=code, now=clock.now_utc())


def roles(conn, household):
    return {(m.user_id, m.role) for m in members(conn, household_id=household.id) if m.status == "active"}


def test_the_creator_is_the_owner(conn, people, flat):
    assert flat.owner_user_id == people[0].id and roles(conn, flat) == {(people[0].id, "owner")}


def test_names_are_one_to_sixty_characters(conn, clock, people):
    for name in ("", "x" * 61):
        with pytest.raises(ValidationError):
            create_household(conn, owner_id=people[0].id, name=name, now=clock.now_utc())


def test_a_code_works_once(conn, clock, people, flat):
    code = create_invitation(conn, household_id=flat.id, created_by=people[0].id, now=clock.now_utc())
    assert join(conn, user_id=people[1].id, code=code.lower(), now=clock.now_utc()).id == flat.id
    with pytest.raises(ValidationError) as error:
        join(conn, user_id=people[2].id, code=code, now=clock.now_utc())
    assert error.value.errors == {"code": INVALID_CODE}


def test_expired_revoked_and_unknown_codes_look_the_same(conn, clock, people, flat):
    expired = create_invitation(conn, household_id=flat.id, created_by=people[0].id,
                                now=clock.now_utc() - timedelta(hours=72))
    revoked = create_invitation(conn, household_id=flat.id, created_by=people[0].id, now=clock.now_utc())
    [active] = list_invitations(conn, household_id=flat.id, now=clock.now_utc())  # the expired one is not listed
    revoke_invitation(conn, household_id=flat.id, invitation_id=active.id, now=clock.now_utc())
    assert list_invitations(conn, household_id=flat.id, now=clock.now_utc()) == []
    for code in (expired, revoked, "ZZZZZZZZZZ"):
        with pytest.raises(ValidationError) as error:
            join(conn, user_id=people[1].id, code=code, now=clock.now_utc())
        assert error.value.errors == {"code": INVALID_CODE}


def test_a_code_just_inside_72_hours_still_works(conn, clock, people, flat):
    code = create_invitation(conn, household_id=flat.id, created_by=people[0].id,
                             now=clock.now_utc() - timedelta(hours=72) + timedelta(seconds=1))
    assert join(conn, user_id=people[1].id, code=code, now=clock.now_utc()).id == flat.id


def test_members_cannot_join_twice(conn, clock, people, flat):
    invite_and_join(conn, clock, flat, people[1])
    with pytest.raises(ConflictError):
        invite_and_join(conn, clock, flat, people[1])


def test_a_household_holds_at_most_eight(conn, clock, people, flat):
    for number in range(7):
        invite_and_join(conn, clock, flat, make_user(conn, clock, f"mate{number}"))
    with pytest.raises(ValidationError, match="full"):
        invite_and_join(conn, clock, flat, people[1])


def test_a_user_belongs_to_at_most_three(conn, clock, people):
    for number in range(3):
        create_household(conn, owner_id=people[1].id, name=f"Place {number}", now=clock.now_utc())
    with pytest.raises(ValidationError, match="three"):
        create_household(conn, owner_id=people[1].id, name="Fourth", now=clock.now_utc())
    other = create_household(conn, owner_id=people[2].id, name="Other", now=clock.now_utc())
    with pytest.raises(ValidationError, match="three"):
        invite_and_join(conn, clock, other, people[1])


def test_leaving_and_removal(conn, clock, people, flat):
    invite_and_join(conn, clock, flat, people[1])
    invite_and_join(conn, clock, flat, people[2])
    assert leave_blockers(conn, household_id=flat.id, user_id=people[1].id) == []
    leave(conn, household_id=flat.id, user_id=people[1].id, now=clock.now_utc())
    remove_member(conn, household_id=flat.id, user_id=people[2].id, now=clock.now_utc())
    statuses = {m.user_id: m.status for m in members(conn, household_id=flat.id)}
    assert statuses == {people[0].id: "active", people[1].id: "left", people[2].id: "removed"}
    assert [h.id for h, active in user_households(conn, user_id=people[1].id)] == [flat.id]
    assert user_households(conn, user_id=people[1].id)[0][1] is False
    invite_and_join(conn, clock, flat, people[1])  # former members may be invited back


def test_the_owner_must_hand_over_before_leaving(conn, clock, people, flat):
    invite_and_join(conn, clock, flat, people[1])
    with pytest.raises(ConflictError, match="ownership"):
        leave(conn, household_id=flat.id, user_id=people[0].id, now=clock.now_utc())
    with pytest.raises(ConflictError):
        remove_member(conn, household_id=flat.id, user_id=people[0].id, now=clock.now_utc())
    with pytest.raises(ValidationError):
        transfer_ownership(conn, household_id=flat.id, version=flat.version, new_owner_id=people[3].id)
    moved = transfer_ownership(conn, household_id=flat.id, version=flat.version, new_owner_id=people[1].id)
    assert moved.owner_user_id == people[1].id
    assert roles(conn, flat) == {(people[0].id, "member"), (people[1].id, "owner")}
    leave(conn, household_id=flat.id, user_id=people[0].id, now=clock.now_utc())
    invite_and_join(conn, clock, flat, people[2])
    with pytest.raises(ConflictError):  # stale version
        transfer_ownership(conn, household_id=flat.id, version=flat.version, new_owner_id=people[2].id)


def test_leave_blockers_are_listed(conn, clock, people, flat):
    invite_and_join(conn, clock, flat, people[1])
    conn.execute("INSERT INTO settlements (household_id, payer_user_id, payee_user_id, initiated_by, amount_cents,"
                 " paid_on, status, created_at) VALUES (?, ?, ?, ?, 500, '2026-09-30', 'pending', 'x')",
                 (flat.id, people[1].id, people[0].id, people[1].id))
    blockers = leave_blockers(conn, household_id=flat.id, user_id=people[1].id)
    assert blockers == ["A settlement involving you is still pending."]
    with pytest.raises(ConflictError, match="pending"):
        leave(conn, household_id=flat.id, user_id=people[1].id, now=clock.now_utc())


def test_archiving_ends_every_membership(conn, clock, people, flat):
    invite_and_join(conn, clock, flat, people[1])
    renamed = rename(conn, household_id=flat.id, version=flat.version, name="Flat 3B (2026)")
    archived = archive(conn, household_id=flat.id, version=renamed.version, now=clock.now_utc())
    assert archived.archived and archived.name == "Flat 3B (2026)"
    assert roles(conn, flat) == set()
    with pytest.raises(ConflictError):
        create_invitation(conn, household_id=flat.id, created_by=people[0].id, now=clock.now_utc())


def test_unknown_households_are_not_found(conn):
    with pytest.raises(NotFoundError):
        get_household(conn, household_id=999)
    with pytest.raises(NotFoundError):
        get_household(conn, household_id=2**63)


def test_dates_are_plain(conn, clock, people, flat):
    assert isinstance(members(conn, household_id=flat.id)[0].joined_on, date)


def test_codes_for_an_archived_household_stop_working(conn, clock, people, flat):
    code = create_invitation(conn, household_id=flat.id, created_by=people[0].id, now=clock.now_utc())
    archive(conn, household_id=flat.id, version=flat.version, now=clock.now_utc())
    with pytest.raises(ValidationError) as error:
        join(conn, user_id=people[1].id, code=code, now=clock.now_utc())
    assert error.value.errors == {"code": INVALID_CODE}
