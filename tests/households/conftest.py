"""A small flat for the Households tests: Ana owns it, Ben and Carla joined. Clock: 30 September 2026."""

from datetime import date

import pytest

from app.application import households
from app.application.context import Actor
from tests.factories import complete_setup, make_user


@pytest.fixture
def flat(conn, clock):
    actors = []
    for name in ("ana", "ben", "carla"):
        user = make_user(conn, clock, name)
        complete_setup(conn, clock, user, tracking_start=date(2026, 9, 1), opening_cents=50000)
        actors.append(Actor(user.id))
    ana, ben, carla = actors
    household = households.create_household(conn, ana, "Flat 3B", clock)
    for member in (ben, carla):
        households.join_household(conn, member, households.invite(conn, ana, household.id, clock), clock)
    return household, ana, ben, carla
