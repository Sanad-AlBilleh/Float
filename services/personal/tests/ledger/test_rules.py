from datetime import date

import pytest

from app.ledger.rules import TransactionDraft, validate_draft
from app.shared.errors import ValidationError

TODAY = date(2026, 9, 30)
START = date(2026, 9, 1)
CATEGORIES = {1, 2, 11}


def check(draft):
    validate_draft(draft, tracking_start=START, today=TODAY, category_ids=CATEGORIES)


def test_valid_expenses_and_income_pass():
    check(TransactionDraft("expense", 2540, date(2026, 9, 20), category_id=1, one_off=True, note="Weekly shop"))
    check(TransactionDraft("income", 75000, START, income_source="allowance"))
    check(TransactionDraft("income", 1000, TODAY, income_source="other"))


@pytest.mark.parametrize(
    "draft, field",
    [
        (TransactionDraft("transfer", 100, TODAY, category_id=1), "kind"),
        (TransactionDraft("expense", 0, TODAY, category_id=1), "amount"),
        (TransactionDraft("expense", 100_000_001, TODAY, category_id=1), "amount"),
        (TransactionDraft("expense", 100, date(2026, 10, 1), category_id=1), "occurred_on"),
        (TransactionDraft("expense", 100, date(2026, 8, 31), category_id=1), "occurred_on"),
        (TransactionDraft("expense", 100, TODAY), "category_id"),
        (TransactionDraft("expense", 100, TODAY, category_id=99), "category_id"),
        (TransactionDraft("expense", 100, TODAY, category_id=1, income_source="other"), "income_source"),
        (TransactionDraft("income", 100, TODAY), "income_source"),
        (TransactionDraft("income", 100, TODAY, income_source="settlement"), "income_source"),
        (TransactionDraft("income", 100, TODAY, income_source="allowance", category_id=1), "category_id"),
        (TransactionDraft("income", 100, TODAY, income_source="allowance", one_off=True), "one_off"),
        (TransactionDraft("expense", 100, TODAY, category_id=1, note="x" * 501), "note"),
    ],
)
def test_each_invalid_draft_names_its_field(draft, field):
    with pytest.raises(ValidationError) as error:
        check(draft)
    assert field in error.value.errors


def test_every_problem_is_reported_at_once():
    with pytest.raises(ValidationError) as error:
        check(TransactionDraft("expense", 0, date(2026, 10, 1), note="x" * 501))
    assert set(error.value.errors) == {"amount", "occurred_on", "category_id", "note"}
