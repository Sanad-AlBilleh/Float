"""Unusual expenses (SRS §4.8, Fixture F, AT-23)."""

from app.insights.api import is_unusual, lower_median, unusual_threshold

FIXTURE_F = [800, 900, 1000, 1000, 1100, 1200, 1300, 1500]


def test_lower_median():
    assert lower_median([3, 1, 2]) == 2 and lower_median([4, 1, 3, 2]) == 2


def test_fixture_f():
    assert unusual_threshold(FIXTURE_F) == 1300
    assert is_unusual(1400, FIXTURE_F) and not is_unusual(1300, FIXTURE_F)


def test_seven_samples_flag_nothing():
    assert unusual_threshold(FIXTURE_F[:7]) is None and not is_unusual(10**6, FIXTURE_F[:7])


def test_identical_history_needs_more_than_a_cent_more():
    same = [1000] * 8
    assert unusual_threshold(same) == 1300  # the 100-cent floor
    assert not is_unusual(1300, same) and is_unusual(1301, same)


def test_a_wide_spread_raises_the_threshold():
    assert unusual_threshold([100, 200, 300, 400, 500, 600, 700, 800]) == 400 + 3 * 200
