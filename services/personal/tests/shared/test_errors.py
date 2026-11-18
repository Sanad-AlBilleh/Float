import pytest

from app.shared.errors import ValidationError


def test_validation_error_keeps_every_field_message():
    error = ValidationError({"amount": "Enter an amount.", "date": "Enter a date as YYYY-MM-DD."})
    assert error.errors == {"amount": "Enter an amount.", "date": "Enter a date as YYYY-MM-DD."}
    assert "amount: Enter an amount." in str(error)


def test_single_field_shortcut():
    assert ValidationError.single("amount", "Enter an amount.").errors == {"amount": "Enter an amount."}


def test_an_empty_validation_error_is_a_programming_mistake():
    with pytest.raises(ValueError):
        ValidationError({})
