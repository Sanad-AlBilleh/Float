"""Who may see or change a household (FR-04, FR-17–19).

Non-members are told the household does not exist (404), exactly as for other people's records.
A member who lacks the owner's role gets 403.
"""

import sqlite3

from app.households import api as households
from app.shared.errors import NotFoundError, PermissionDeniedError


def require_viewer(conn: sqlite3.Connection, user_id: int, household_id: int) -> households.Member:
    """Current or former members may read the household's history (FR-19)."""
    households.get_household(conn, household_id=household_id)
    member = households.membership(conn, household_id=household_id, user_id=user_id)
    if member is None:
        raise NotFoundError("No such household.")
    return member


def require_member(conn: sqlite3.Connection, user_id: int, household_id: int) -> households.Member:
    member = require_viewer(conn, user_id, household_id)
    if member.status != "active":
        raise NotFoundError("No such household.")
    return member


def require_owner(conn: sqlite3.Connection, user_id: int, household_id: int) -> households.Member:
    member = require_member(conn, user_id, household_id)
    if member.role != "owner":
        raise PermissionDeniedError("Only the household's owner can do that.")
    return member
