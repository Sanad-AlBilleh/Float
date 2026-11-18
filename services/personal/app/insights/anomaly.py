"""Unusual expenses (SRS §4.8): median and median absolute deviation, all in integer cents."""

from collections.abc import Sequence

MIN_HISTORY = 8
MAD_FLOOR_CENTS = 100  # stops an identical history from flagging a tiny increase


def lower_median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def unusual_threshold(history: Sequence[int]) -> int | None:
    """The amount above which an expense is unusual, or None with fewer than 8 comparable expenses."""
    if len(history) < MIN_HISTORY:
        return None
    middle = lower_median(history)
    spread = lower_median([abs(value - middle) for value in history])
    return middle + 3 * max(spread, MAD_FLOOR_CENTS)


def is_unusual(amount_cents: int, history: Sequence[int]) -> bool:
    threshold = unusual_threshold(history)
    return threshold is not None and amount_cents > threshold
