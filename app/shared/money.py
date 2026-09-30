"""Exact euro amounts as integer cents (SRS §2). Never use float for money."""

import re

from app.shared.errors import ValidationError

MAX_CENTS = 100_000_000  # €1,000,000.00, the largest magnitude Float accepts
_AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:[.,]([0-9]+))?")


def parse_money(
    text: str | None,
    *,
    field: str = "amount",
    allow_zero: bool = False,
    allow_negative: bool = False,
) -> int:
    """Parse input such as ``12.5``, ``12,50``, ``€ 7`` or ``1 234,56`` into integer cents.

    One decimal separator (``.`` or ``,``) followed by at most two digits is accepted.
    Anything else is rejected rather than rounded or guessed: ``1,234`` is an error, not 1234.
    """
    cleaned = "" if text is None else str(text)
    for symbol in ("€", " ", " "):
        cleaned = cleaned.replace(symbol, "")
    cleaned = cleaned.replace("−", "-")
    if not cleaned:
        raise ValidationError.single(field, "Enter an amount.")
    match = _AMOUNT.fullmatch(cleaned)
    if match is None:
        raise ValidationError.single(field, "Enter an amount like 12.50.")
    sign, whole, fraction = match.groups()
    fraction = fraction or ""
    if len(fraction) > 2:
        raise ValidationError.single(field, "Use at most two decimal places.")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
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
