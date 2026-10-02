"""Category budgets: templates, overrides, and states (FR-16, FR-31, AT-12)."""

from datetime import date

import pytest

from app.planning.api import budget_state, effective_limit, set_override, set_template
from app.shared.errors import ValidationError
from tests.factories import make_user

SEPTEMBER, OCTOBER = date(2026, 9, 1), date(2026, 10, 1)
GROCERIES = 1


@pytest.mark.parametrize(
    "consumption, limit, state",
    [(6000, 5000, "over"), (4000, 5000, "warning"), (3999, 5000, "ok"), (5000, 5000, "warning"), (0, 0, "ok"),
     (1, 0, "over"), (100, None, None)],
)
def test_budget_state(consumption, limit, state):
    assert budget_state(consumption, limit) == state


def test_a_template_applies_to_every_cycle_and_an_override_wins(conn, clock):
    ana = make_user(conn, clock)
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER) is None
    set_template(conn, user_id=ana.id, category_id=GROCERIES, limit_cents=20000)
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=OCTOBER) == 20000
    set_override(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER, limit_cents=0)
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER) == 0
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=OCTOBER) == 20000
    set_template(conn, user_id=ana.id, category_id=GROCERIES, limit_cents=25000)  # replaces, never duplicates
    set_override(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER, limit_cents=None)
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER) == 25000
    set_template(conn, user_id=ana.id, category_id=GROCERIES, limit_cents=None)
    assert effective_limit(conn, user_id=ana.id, category_id=GROCERIES, cycle_start=SEPTEMBER) is None


def test_limits_are_never_negative(conn, clock):
    ana = make_user(conn, clock)
    with pytest.raises(ValidationError):
        set_template(conn, user_id=ana.id, category_id=GROCERIES, limit_cents=-1)
