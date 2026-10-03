"""Net balances and the settle-up plan (SRS §4.4, Fixtures A and G, AT-16)."""

from hypothesis import given
from hypothesis import strategies as st

from app.households.api import Transfer, compute_nets, simplify

ANA, BEN, CARLA = 1, 2, 3


def test_fixture_a_nets_and_plan():
    expenses = [(ANA, 3000, {ANA: 1000, BEN: 1000, CARLA: 1000}), (BEN, 9000, {ANA: 3000, BEN: 3000, CARLA: 3000})]
    nets = compute_nets([ANA, BEN, CARLA], expenses, [])
    assert nets == {ANA: -1000, BEN: 5000, CARLA: -4000}
    assert simplify(nets) == [Transfer(CARLA, BEN, 4000), Transfer(ANA, BEN, 1000)]


def test_confirmed_settlements_move_the_nets():
    nets = compute_nets([ANA, BEN], [(BEN, 2000, {ANA: 1000, BEN: 1000})], [(ANA, BEN, 1000)])
    assert nets == {ANA: 0, BEN: 0} and simplify(nets) == []


def test_fixture_g():
    assert simplify({1: 6000, 2: -1000, 3: -2000, 4: -3000}) == [
        Transfer(4, 1, 3000), Transfer(3, 1, 2000), Transfer(2, 1, 1000)]


def test_ties_go_to_the_lower_user_id():
    assert simplify({1: 500, 2: 500, 3: -500, 4: -500}) == [Transfer(3, 1, 500), Transfer(4, 2, 500)]


@st.composite
def households(draw):
    members = list(range(1, draw(st.integers(2, 8)) + 1))
    expenses = []
    for _ in range(draw(st.integers(0, 12))):
        payer = draw(st.sampled_from(members))
        sharers = draw(st.lists(st.sampled_from(members), min_size=1, unique=True))
        shares = {user: draw(st.integers(0, 50_000)) for user in sharers}
        expenses.append((payer, sum(shares.values()), shares))
    settlements = [(a, b, draw(st.integers(1, 50_000))) for a, b in
                   draw(st.lists(st.tuples(st.sampled_from(members), st.sampled_from(members)), max_size=5)) if a != b]
    return members, expenses, settlements


@given(households())
def test_nets_sum_to_zero_and_the_plan_settles_everyone(case):
    members, expenses, settlements = case
    nets = compute_nets(members, expenses, settlements)
    assert sum(nets.values()) == 0
    plan = simplify(nets)
    after = dict(nets)
    for transfer in plan:
        assert transfer.amount_cents > 0 and transfer.from_user != transfer.to_user
        after[transfer.from_user] += transfer.amount_cents
        after[transfer.to_user] -= transfer.amount_cents
    assert not any(after.values())
    assert len(plan) <= max(0, sum(1 for net in nets.values() if net) - 1)
