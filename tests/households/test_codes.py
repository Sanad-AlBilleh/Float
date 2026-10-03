"""Invitation codes (FR-18)."""

import pytest

from app.households.api import CROCKFORD, INVALID_CODE, hash_code, new_invite_code, normalize_code
from app.shared.errors import ValidationError


def test_codes_are_ten_crockford_characters():
    codes = {new_invite_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(len(code) == 10 and set(code) <= set(CROCKFORD) for code in codes)


def test_normalizing_forgives_case_spacing_and_lookalikes():
    assert normalize_code(" ab-cd efgh jk ") == "ABCDEFGHJK"
    assert normalize_code("oOiIlL0123") == "0011110123"


@pytest.mark.parametrize("raw", ["", "SHORT", "ABCDEFGHJKM", "ABCDEFGHJU", None, "ÄBCDEFGHJK"])
def test_malformed_codes_get_the_generic_message(raw):
    with pytest.raises(ValidationError) as error:
        normalize_code(raw)
    assert error.value.errors == {"code": INVALID_CODE}


def test_only_a_hash_is_kept():
    assert len(hash_code("ABCDEFGHJK")) == 64 and hash_code("ABCDEFGHJK") != "ABCDEFGHJK"
