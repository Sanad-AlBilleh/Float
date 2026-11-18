"""Test people. Users live in the personal service, so here a user is just an ID."""

import itertools
from dataclasses import dataclass
from datetime import date

from app.application.context import Actor

_ids = itertools.count(1001)


@dataclass(frozen=True)
class User:
    id: int


def make_user(conn, clock, name: str = "ana") -> User:
    """A user for the domain tests, which only need a distinct ID (the A1 signature, kept)."""
    return User(next(_ids))


def make_member(personal, user_id: int, name: str, *, tracking_start: date | None = date(2026, 9, 1),
                allowance_day: int = 1) -> Actor:
    """A signed-up user the personal stand-in knows; ``tracking_start=None`` means setup is not complete."""
    personal.add_user(user_id, name, tracking_start=tracking_start, allowance_day=allowance_day)
    return Actor(user_id)
