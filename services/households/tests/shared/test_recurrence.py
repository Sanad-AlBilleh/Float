from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.dates import last_day_of_month
from app.shared.errors import ValidationError
from app.shared.recurrence import Rule, candidate, count_before, expand, split_rule

D = date


def test_fixture_e_monthly_keeps_the_anchor_day_without_drift():
    rule = Rule("monthly", 1, D(2027, 1, 31))
    assert expand(rule, D(2027, 1, 1), D(2027, 5, 1)) == [
        D(2027, 1, 31), D(2027, 2, 28), D(2027, 3, 31), D(2027, 4, 30),
    ]


def test_fixture_e_leap_year():
    assert expand(Rule("monthly", 1, D(2028, 1, 31)), D(2028, 2, 1), D(2028, 3, 1)) == [D(2028, 2, 29)]


def test_fixture_e_every_two_weeks():
    assert D(2026, 9, 4).strftime("%A") == "Friday"
    assert expand(Rule("weekly", 2, D(2026, 9, 4)), D(2026, 9, 1), D(2026, 10, 20)) == [
        D(2026, 9, 4), D(2026, 9, 18), D(2026, 10, 2), D(2026, 10, 16),
    ]


def test_fixture_e_every_three_months():
    assert expand(Rule("monthly", 3, D(2026, 10, 15)), D(2026, 10, 1), D(2027, 5, 1)) == [
        D(2026, 10, 15), D(2027, 1, 15), D(2027, 4, 15),
    ]


def test_fixture_e_count_is_measured_from_the_anchor():
    rule = Rule("monthly", 1, D(2026, 11, 5), count=3)
    assert expand(rule, D(2026, 12, 1), D(2027, 12, 1)) == [D(2026, 12, 5), D(2027, 1, 5)]


def test_until_is_inclusive_and_window_end_is_exclusive():
    weekly = Rule("weekly", 1, D(2026, 9, 4), until=D(2026, 9, 18))
    assert expand(weekly, D(2026, 9, 1), D(2026, 12, 1)) == [D(2026, 9, 4), D(2026, 9, 11), D(2026, 9, 18)]
    monthly = Rule("monthly", 1, D(2026, 9, 25))
    assert expand(monthly, D(2026, 9, 1), D(2026, 10, 25)) == [D(2026, 9, 25)]


def test_once_produces_only_its_anchor():
    rule = Rule("once", 1, D(2026, 9, 25))
    assert expand(rule, D(2026, 9, 1), D(2027, 1, 1)) == [D(2026, 9, 25)]
    assert expand(rule, D(2026, 9, 26), D(2027, 1, 1)) == []


def test_a_window_starting_on_an_occurrence_includes_it():
    fortnightly = Rule("weekly", 2, D(2026, 9, 4))
    assert expand(fortnightly, D(2026, 9, 18), D(2026, 10, 3)) == [D(2026, 9, 18), D(2026, 10, 2)]
    gym = Rule("monthly", 1, D(2026, 7, 5))
    assert expand(gym, D(2026, 9, 5), D(2026, 10, 6)) == [D(2026, 9, 5), D(2026, 10, 5)]


def test_count_before_counts_valid_occurrences():
    gym = Rule("monthly", 1, D(2026, 7, 5))
    assert count_before(gym, D(2026, 10, 5)) == 3
    assert count_before(gym, D(2026, 7, 5)) == 0
    assert count_before(Rule("monthly", 1, D(2026, 7, 5), count=2), D(2027, 1, 1)) == 2


@pytest.mark.parametrize(
    "fields, bad_field",
    [
        ({"freq": "daily", "interval": 1}, "freq"),
        ({"freq": "weekly", "interval": 0}, "interval"),
        ({"freq": "weekly", "interval": 53}, "interval"),
        ({"freq": "monthly", "interval": 13}, "interval"),
        ({"freq": "once", "interval": 2}, "interval"),
        ({"freq": "monthly", "interval": 1, "until": D(2026, 12, 1), "count": 3}, "until"),
        ({"freq": "once", "interval": 1, "count": 1}, "until"),
        ({"freq": "monthly", "interval": 1, "until": D(2026, 8, 31)}, "until"),
        ({"freq": "monthly", "interval": 1, "count": 0}, "count"),
        ({"freq": "monthly", "interval": 1, "count": 501}, "count"),
    ],
)
def test_invalid_rules_are_rejected(fields, bad_field):
    with pytest.raises(ValidationError) as error:
        Rule(anchor=D(2026, 9, 1), **fields)
    assert bad_field in error.value.errors


@st.composite
def rules(draw):
    freq = draw(st.sampled_from(["once", "weekly", "monthly"]))
    interval = 1 if freq == "once" else draw(st.integers(1, 52 if freq == "weekly" else 12))
    anchor = draw(st.dates(D(2020, 1, 1), D(2030, 12, 31)))
    ending = "none" if freq == "once" else draw(st.sampled_from(["none", "until", "count"]))
    until = draw(st.dates(anchor, D(2035, 12, 31))) if ending == "until" else None
    count = draw(st.integers(1, 40)) if ending == "count" else None
    return Rule(freq, interval, anchor, until, count)


starts = st.dates(D(2019, 1, 1), D(2036, 1, 1))


@given(rules(), starts, st.integers(0, 800))
def test_results_are_sorted_unique_and_inside_the_window(rule, start, length):
    end = start + timedelta(days=length)
    result = expand(rule, start, end)
    assert result == sorted(set(result))
    assert all(start <= day < end for day in result)
    if rule.until is not None:
        assert all(day <= rule.until for day in result)


@given(rules(), starts, st.integers(0, 400), st.integers(0, 400))
def test_adjacent_windows_concatenate(rule, start, first, second):
    middle = start + timedelta(days=first)
    end = middle + timedelta(days=second)
    assert expand(rule, start, end) == expand(rule, start, middle) + expand(rule, middle, end)


@given(rules())
def test_occurrences_are_the_rule_candidates_in_order(rule):
    dates = expand(rule, rule.anchor, rule.anchor + timedelta(days=3 * 366))
    assert dates == [candidate(rule, k) for k in range(len(dates))]
    if rule.freq == "monthly":
        assert all(day.day == min(rule.anchor.day, last_day_of_month(day.year, day.month)) for day in dates)


@given(rules(), st.integers(0, 30))
def test_every_occurrence_is_found_by_a_window_starting_on_it(rule, k):
    occurrences = expand(rule, rule.anchor, rule.anchor + timedelta(days=3 * 366))
    if k < len(occurrences):
        day = occurrences[k]
        assert expand(rule, day, day + timedelta(days=1)) == [day]


@given(rules())
def test_count_limits_the_total_number_of_occurrences(rule):
    everything = expand(rule, rule.anchor, rule.anchor + timedelta(days=45 * 366))
    if rule.count is not None:
        assert len(everything) == rule.count


def test_split_ends_the_old_rule_the_day_before():
    rule = Rule("monthly", 1, date(2026, 7, 5))
    assert split_rule(rule, date(2026, 10, 5)) == (Rule("monthly", 1, date(2026, 7, 5), until=date(2026, 10, 4)), None)


def test_split_hands_the_remaining_count_to_the_new_rule():
    rule = Rule("monthly", 1, date(2026, 7, 5), count=6)
    shortened, remaining = split_rule(rule, date(2026, 10, 5))
    assert shortened.until == date(2026, 10, 4) and shortened.count is None and remaining == 3
    assert expand(shortened, rule.anchor, date(2027, 7, 1)) == expand(rule, rule.anchor, date(2026, 10, 5))


@pytest.mark.parametrize("split_on", [date(2026, 7, 5), date(2026, 7, 1)])
def test_split_at_or_before_the_anchor_is_refused(split_on):
    with pytest.raises(ValidationError) as error:
        split_rule(Rule("monthly", 1, date(2026, 7, 5)), split_on)
    assert set(error.value.errors) == {"anchor_date"}
