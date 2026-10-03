"""Pure household rules: invitation codes, names, and net balances (FR-17–18, SRS §4.4)."""

import hashlib
import secrets
from collections.abc import Iterable, Mapping
from datetime import timedelta

from app.shared.errors import ValidationError

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
