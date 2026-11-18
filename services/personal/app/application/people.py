"""Display names of users, for activity feeds and alerts. Users belong to this service."""

from app.db.connection import Connection
from app.identity import api as identity
from app.shared.errors import NotFoundError


def display_names(conn: Connection, user_ids) -> dict[int, str]:
    names = {}
    for user_id in set(user_ids):
        try:
            names[user_id] = identity.get_user(conn, user_id).display_name
        except NotFoundError:
            names[user_id] = f"Member #{user_id}"
    return names
