"""Pure household rules: invitation codes, names, and net balances (FR-17–18, SRS §4.4)."""

import hashlib
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

from app.shared.errors import ValidationError
from app.shared.money import format_money

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # no I, L, O, or U, so codes are easy to read aloud
CODE_LENGTH = 10
INVITE_TTL = timedelta(hours=72)
MAX_MEMBERS = 8
MAX_HOUSEHOLDS = 3
NAME_LIMIT = 60
INVALID_CODE = "That invitation code is not valid. Ask a member of the household for a new one."
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_invite_code() -> str:
    return "".join(secrets.choice(CROCKFORD) for _ in range(CODE_LENGTH))


def normalize_code(raw: str | None) -> str:
    """Uppercase, drop spaces and hyphens, and read O as 0 and I or L as 1."""
    code = "".join(ch for ch in (raw or "").upper() if ch not in " -").translate(_LOOKALIKES)
    if len(code) != CODE_LENGTH or any(ch not in CROCKFORD for ch in code):
        raise ValidationError.single("code", INVALID_CODE)
    return code


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def validate_household_name(name: str) -> None:
    if not 1 <= len(name) <= NAME_LIMIT:
        raise ValidationError.single("name", f"Enter a name of 1 to {NAME_LIMIT} characters.")


def compute_nets(members: Iterable[int], expenses: Iterable[tuple[int, int, Mapping[int, int]]],
                 settlements: Iterable[tuple[int, int, int]]) -> dict[int, int]:
    """SRS §4.4. ``expenses``: (payer, amount, {user: share}); ``settlements``: confirmed (payer, payee, amount).

    Positive means the others owe the member. The nets always sum to zero.
    """
    nets = {member: 0 for member in members}
    for payer, amount, shares in expenses:
        nets[payer] = nets.get(payer, 0) + amount
        for user, share in shares.items():
            nets[user] = nets.get(user, 0) - share
    for payer, payee, amount in settlements:
        nets[payer] = nets.get(payer, 0) + amount
        nets[payee] = nets.get(payee, 0) - amount
    return nets


SPLIT_METHODS = ("equal", "exact", "percentage", "shares")
TEMPLATE_METHODS = ("equal", "percentage", "shares")  # a household bill's amount may change, so no "exact"
DESCRIPTION_LIMIT = 100


@dataclass(frozen=True)
class SplitEntry:
    """One participant and their method input: cents (exact), basis points (percentage), a weight (shares),
    or None (equal)."""

    user_id: int
    value: int | None = None


def allocate(amount_cents: int, method: str, entries: Sequence[SplitEntry]) -> dict[int, int]:
    """Split ``amount_cents`` exactly (SRS §4.3): the shares always sum to the amount."""
    if method not in SPLIT_METHODS:
        raise ValidationError.single("split_method", "Choose equal, exact, percentage, or shares.")
    ordered = sorted(entries, key=lambda entry: entry.user_id)
    if not ordered or len({entry.user_id for entry in ordered}) != len(ordered):
        raise ValidationError.single("participants", "Choose each participant once.")
    if method == "exact":
        values = [entry.value for entry in ordered]
        if any(value is None or value < 0 for value in values):
            raise ValidationError.single("split", "Enter an amount of zero or more for each participant.")
        if sum(values) != amount_cents:
            raise ValidationError.single(
                "split", f"The amounts add up to {format_money(sum(values))}, not {format_money(amount_cents)}."
            )
        shares = [int(value) for value in values]
    else:
        if method == "equal":
            weights = [1] * len(ordered)
        else:
            weights = [entry.value for entry in ordered]
            low, high = (0, 10_000) if method == "percentage" else (1, 100)
            if any(weight is None or not low <= weight <= high for weight in weights):
                raise ValidationError.single("split", "Enter a valid percentage or share for each participant.")
            if method == "percentage" and sum(weights) != 10_000:
                raise ValidationError.single("split", "Percentages must add up to exactly 100%.")
        total = sum(weights)
        shares = [amount_cents * weight // total for weight in weights]
        ranking = sorted(range(len(ordered)), key=lambda i: (-(amount_cents * weights[i] % total), ordered[i].user_id))
        for index in ranking[: amount_cents - sum(shares)]:
            shares[index] += 1
    if not any(shares):
        raise ValidationError.single("split", "At least one participant must have a positive share.")
    return {entry.user_id: share for entry, share in zip(ordered, shares, strict=True)}
