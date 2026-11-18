"""Exact euro amounts as integer cents (SRS §2). Never use float for money."""

import re

from app.shared.errors import ValidationError

MAX_CENTS = 100_000_000  # €1,000,000.00, the largest magnitude Float accepts
MAX_WHOLE_DIGITS = 9  # checked before int(), so absurdly long input is an error, not a crash
GROUP_SPACES = " \u00a0\u202f"  # space, no-break space, narrow no-break space
_NUMBER = re.compile(
    r"(?P<whole>[0-9]+|[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+)(?:[.,](?P<fraction>[0-9]+))?"
)


def parse_money(
    text: str | None,
    *,
    field: str = "amount",
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> int:
    """Parse input such as ``12.5``, ``12,50``, ``€ 7`` or ``1 234,56`` into integer cents.

    One decimal separator (``.`` or ``,``) followed by at most two digits is accepted, and spaces
    only between groups of three digits. Anything else is rejected rather than guessed: ``1,234``
    and ``12 50`` are errors, not 1234 or 1250.
    """
    raw = ("" if text is None else str(text)).strip().replace("\u2212", "-")
    sign = ""
    if raw[:1] in ("+", "-"):
        sign, raw = raw[0], raw[1:].lstrip()
    if raw.startswith("€"):
        raw = raw[1:].lstrip()
    elif raw.endswith("€"):
        raw = raw[:-1].rstrip()
    if not raw:
        raise ValidationError.single(field, "Enter an amount.")
    match = _NUMBER.fullmatch(raw)
    if match is None:
        if any(space in raw for space in GROUP_SPACES):
            raise ValidationError.single(field, "Use spaces only between groups of three digits, like 1 234,56.")
        raise ValidationError.single(field, "Enter an amount like 12.50.")
    whole = "".join(ch for ch in match["whole"] if ch.isdigit()).lstrip("0")
    fraction = match["fraction"] or ""
    if len(fraction) > 2:
        raise ValidationError.single(field, "Use at most two decimal places.")
    if len(whole) > MAX_WHOLE_DIGITS:
        raise ValidationError.single(field, "Amounts are limited to €1,000,000.00.")
    cents = int(whole or "0") * 100 + int(fraction.ljust(2, "0"))
    if sign == "-":
        cents = -cents
    if abs(cents) > MAX_CENTS:
        raise ValidationError.single(field, "Amounts are limited to €1,000,000.00.")
    if cents < 0 and not allow_negative:
        raise ValidationError.single(field, "Enter a positive amount.")
    if cents == 0 and not allow_zero:
        raise ValidationError.single(field, "Enter an amount greater than zero.")
    return cents


def format_money(cents: int) -> str:
    """Display format: ``123456`` → ``€1,234.56`` and ``-500`` → ``-€5.00``."""
    sign = "-" if cents < 0 else ""
    euros, remainder = divmod(abs(cents), 100)
    return f"{sign}€{euros:,}.{remainder:02d}"


def cents_to_input(cents: int) -> str:
    """Form-field format that ``parse_money`` reads back exactly: ``123456`` → ``1234.56``."""
    sign = "-" if cents < 0 else ""
    euros, remainder = divmod(abs(cents), 100)
    return f"{sign}{euros}.{remainder:02d}"
