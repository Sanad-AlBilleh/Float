"""Request bodies for /api/v1. Money is integer cents and dates are YYYY-MM-DD (FR-34).

Bodies are parsed inside each handler, after authorization, so a stranger always gets 404 and never
learns whether their request body was valid.
"""

from datetime import date
from typing import Any, Literal, TypeVar

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError as PydanticError

Model = TypeVar("Model", bound=BaseModel)


def parse(model: type[Model], payload: Any) -> Model:
    try:
        return model.model_validate(payload if payload is not None else {})
    except PydanticError as error:
        raise RequestValidationError([{**e, "loc": ("body", *e["loc"])} for e in error.errors()]) from None


def body_doc(model: type[BaseModel]) -> dict:
    """OpenAPI documentation for a body that is parsed by hand."""
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": model.model_json_schema()}}}}


class Credentials(BaseModel):
    username: str
    password: str


class Registration(Credentials):
    display_name: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class SetupIn(BaseModel):
    tracking_start: date
    opening_balance_cents: int
    allowance_day: int
    planned_allowance_cents: int = 75000
    allowance_included: bool = False


class PlannedAllowanceIn(BaseModel):
    planned_allowance_cents: int


class TransactionIn(BaseModel):
    kind: Literal["income", "expense"]
    amount_cents: int
    occurred_on: date
    category_id: int | None = None
    income_source: str | None = None
    one_off: bool = False
    note: str = ""


class Versioned(BaseModel):
    version: int


class TransactionEdit(TransactionIn, Versioned):
    pass


class SeriesIn(BaseModel):
    name: str
    amount_cents: int
    category_id: int
    freq: Literal["once", "weekly", "monthly"]
    interval: int = 1
    anchor_date: date
    until: date | None = None
    count: int | None = None


class SplitIn(SeriesIn, Versioned):
    pass


class OccurrenceEdit(Versioned):
    amount_cents: int
    due_date: date


class PaymentIn(Versioned):
    paid_on: date | None = None


class GoalIn(BaseModel):
    name: str
    target_cents: int
    target_date: date | None = None
    priority: int = 2
    auto_reserve: bool = False


class GoalEdit(GoalIn, Versioned):
    pass


class MovementIn(BaseModel):
    delta_cents: int


class LimitIn(BaseModel):
    limit_cents: int | None
    scope: Literal["template", "cycle"] = "template"


class NameIn(BaseModel):
    name: str


class RenameIn(NameIn, Versioned):
    pass


class CodeIn(BaseModel):
    code: str


class TransferIn(Versioned):
    new_owner_id: int


class Participant(BaseModel):
    user_id: int
    value: int | None = None


class ExpenseIn(BaseModel):
    amount_cents: int
    spent_on: date
    category_id: int
    description: str
    one_off: bool = False
    split_method: Literal["equal", "exact", "percentage", "shares"] = "equal"
    participants: list[Participant]


class ExpenseEdit(ExpenseIn, Versioned):
    pass


class SettlementIn(BaseModel):
    payer_user_id: int
    payee_user_id: int
    amount_cents: int
    paid_on: date


class ReasonIn(Versioned):
    reason: str = ""


class HouseholdBillIn(SeriesIn):
    split_method: Literal["equal", "percentage", "shares", "exact"] = "equal"
    participants: list[Participant]
