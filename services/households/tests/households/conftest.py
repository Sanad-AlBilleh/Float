"""A small flat for the Households tests: Ana owns it, Ben and Carla joined. Clock: 30 September 2026."""

import pytest

from app.application import households
from tests.factories import make_member


@pytest.fixture
def flat(conn, clock, personal):
    ana, ben, carla = (make_member(personal, i, name) for i, name in ((1, "Ana"), (2, "Ben"), (3, "Carla")))
    household = households.create_household(conn, ana, "Flat 3B", clock)
    for member in (ben, carla):
        households.join_household(conn, personal, member, households.invite(conn, ana, household.id, clock), clock)
    return household, ana, ben, carla
