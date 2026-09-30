import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS, cents_to_input, format_money, parse_money
from app.web.templating import templates


@pytest.mark.parametrize(
    "text, cents",
    [
        ("12", 1200),
        ("12.5", 1250),
        ("12.50", 1250),
        ("12,50", 1250),
        ("0.01", 1),
        ("25.40", 2540),
        (" 7 ", 700),
        ("€7", 700),
        ("€ 1 234,56", 123456),
        ("1000000.00", MAX_CENTS),
    ],
)
def test_parses_exact_cents(text, cents):
    assert parse_money(text) == cents


@pytest.mark.parametrize(
    "text, message",
    [
        (None, "Enter an amount."),
        ("", "Enter an amount."),
        ("abc", "Enter an amount like 12.50."),
        ("12.", "Enter an amount like 12.50."),
        (".5", "Enter an amount like 12.50."),
        ("1.000.000", "Enter an amount like 12.50."),
        ("1.234", "Use at most two decimal places."),
        ("1,234", "Use at most two decimal places."),
        ("0", "Enter an amount greater than zero."),
        ("-5", "Enter a positive amount."),
        ("1000000.01", "Amounts are limited to €1,000,000.00."),
    ],
)
def test_rejects_invalid_input_with_a_clear_message(text, message):
    with pytest.raises(ValidationError) as error:
        parse_money(text, field="amount")
    assert error.value.errors == {"amount": message}


def test_zero_and_negative_amounts_are_opt_in():
    assert parse_money("0", allow_zero=True) == 0
    assert parse_money("-12.30", allow_negative=True) == -1230
    assert parse_money("−4", allow_negative=True) == -400  # typographic minus sign
    assert parse_money("-1000000", allow_negative=True) == -MAX_CENTS


def test_formats_amounts_for_display():
    assert format_money(0) == "€0.00"
    assert format_money(5) == "€0.05"
    assert format_money(123456) == "€1,234.56"
    assert format_money(-500) == "-€5.00"
    assert format_money(MAX_CENTS) == "€1,000,000.00"


def test_money_filter_is_available_in_templates():
    assert templates.env.from_string("{{ 123456|money }}").render() == "€1,234.56"


@given(st.integers(min_value=-MAX_CENTS, max_value=MAX_CENTS))
def test_form_values_round_trip_exactly(cents):
    assert parse_money(cents_to_input(cents), allow_zero=True, allow_negative=True) == cents
