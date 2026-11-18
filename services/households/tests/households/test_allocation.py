"""Exact split allocation by largest remainder (SRS §4.3, Fixture D, AT-14)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.households.api import SplitEntry, allocate
from app.shared.errors import ValidationError


def entries(*values, users=None):
    users = users or range(1, len(values) + 1)
    return [SplitEntry(user, value) for user, value in zip(users, values)]


def test_fixture_d_equal():
    assert allocate(10000, "equal", entries(None, None, None)) == {1: 3334, 2: 3333, 3: 3333}


def test_fixture_d_percentage():
    assert allocate(1000, "percentage", entries(3333, 3333, 3334)) == {1: 333, 2: 333, 3: 334}


def test_fixture_d_shares():
    assert allocate(1001, "shares", entries(2, 1, 1)) == {1: 501, 2: 250, 3: 250}


def test_fixture_d_exact():
    assert allocate(10000, "exact", entries(4000, 3500, 2500)) == {1: 4000, 2: 3500, 3: 2500}
    with pytest.raises(ValidationError, match="€99.99"):
        allocate(10000, "exact", entries(4000, 3500, 2499))


def test_fixture_d_percentages_must_total_100():
    with pytest.raises(ValidationError, match="100%"):
        allocate(10000, "percentage", entries(5000, 4999))


def test_input_order_does_not_matter():
    assert allocate(10000, "equal", entries(None, None, None, users=[3, 1, 2])) == {1: 3334, 2: 3333, 3: 3333}


@pytest.mark.parametrize("method, values", [
    ("bogus", (None,)), ("shares", (0, 1)), ("shares", (101, 1)), ("percentage", (-1, 10001)),
    ("exact", (None, 100)), ("exact", (-1, 101)), ("percentage", (10000, 0)), ("exact", (0, 0)),
])
def test_invalid_splits_are_rejected(method, values):
    amount = 100 if method == "exact" and values != (0, 0) else 1
    if (method, values) == ("percentage", (10000, 0)):
        assert allocate(100, method, entries(*values)) == {1: 100, 2: 0}  # a zero share is allowed
        return
    with pytest.raises(ValidationError):
        allocate(amount, method, entries(*values))


def test_each_participant_once():
    with pytest.raises(ValidationError):
        allocate(100, "equal", [SplitEntry(1, None), SplitEntry(1, None)])
    with pytest.raises(ValidationError):
        allocate(100, "equal", [])


weights = st.lists(st.integers(1, 100), min_size=1, max_size=8)


@given(st.integers(1, 100_000_000), st.sampled_from(["equal", "shares"]), weights)
def test_shares_sum_exactly_and_stay_within_a_cent(amount, method, values):
    split = entries(*values) if method == "shares" else entries(*[None] * len(values))
    result = allocate(amount, method, split)
    assert sum(result.values()) == amount
    weight_of = {entry.user_id: (entry.value if method == "shares" else 1) for entry in split}
    total = sum(weight_of.values())
    for user, share in result.items():
        assert abs(share * total - amount * weight_of[user]) < total  # within one cent of exact
    assert allocate(amount, method, list(reversed(split))) == result  # deterministic


@given(st.integers(1, 1_000_000), st.lists(st.integers(0, 10_000), min_size=2, max_size=8))
def test_percentages_never_give_a_cent_to_a_zero_weight(amount, raw):
    raw[-1] = 0
    total = sum(raw[:-1])
    if total == 0:
        return
    basis = [value * 10_000 // total for value in raw[:-1]]
    basis[0] += 10_000 - sum(basis)
    result = allocate(amount, "percentage", entries(*basis, 0))
    assert sum(result.values()) == amount and result[len(raw)] == 0
