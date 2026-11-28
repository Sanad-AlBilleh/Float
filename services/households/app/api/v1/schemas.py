"""Request bodies for /api/v1. Money is integer cents and dates are YYYY-MM-DD (FR-34).

Bodies are parsed inside each handler, after authorization, so a stranger always gets 404 and never
learns whether their request body was valid.
"""

from datetime import date
from typing import Annotated, Any, Literal, TypeVar

from fastapi.exceptions import RequestValidationError
from pydantic import AfterValidator, BaseModel, Field
from pydantic import ValidationError as PydanticError

from app.shared.dates import EARLIEST, LATEST, RANGE_MESSAGE


def _in_range(day: date) -> date:
    if not EARLIEST <= day <= LATEST:
        raise ValueError(RANGE_MESSAGE)
    return day


Day = Annotated[date, AfterValidator(_in_range)]  # the same range the pages accept
Id = Annotated[int, Field(ge=1, le=2**31 - 1)]  # SQL Server INT: larger IDs cannot exist, so they are refused
Cents = Annotated[int, Field(ge=-(10**9), le=10**9)]  # the services apply the exact money limits

Model = TypeVar("Model", bound=BaseModel)


def _unstorable(value: Any, loc: tuple = ()) -> list[dict]:
    """Strings SQL Server cannot store as sent: NUL and other control characters (newline and tab are
    allowed), and lone surrogates, which are not valid Unicode. They are refused as a 422 here, once for
    every body, instead of failing later in the database driver as a 500."""
    if isinstance(value, str):
        bad = any(ch not in "\n\r\t" and (ord(ch) < 0x20 or ord(ch) == 0x7F or 0xD800 <= ord(ch) <= 0xDFFF)
                  for ch in value)
        return [{"type": "value_error", "loc": ("body", *loc), "input": None,
                 "msg": "Remove control characters and invalid Unicode from this text."}] if bad else []
    if isinstance(value, dict):
        return [e for key, item in value.items() for e in _unstorable(item, (*loc, str(key)))]
    if isinstance(value, list):
        return [e for index, item in enumerate(value) for e in _unstorable(item, (*loc, index))]
    return []


def parse(model: type[Model], payload: Any) -> Model:
    if errors := _unstorable(payload):
        raise RequestValidationError(errors)
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
    tracking_start: Day
    opening_balance_cents: Cents
    allowance_day: Annotated[int, Field(ge=1, le=31)]
    planned_allowance_cents: Cents = 75000
    allowance_included: bool = False
    monthly_savings_cents: Cents = 0


class PlannedAllowanceIn(BaseModel):
    planned_allowance_cents: Cents


class TransactionIn(BaseModel):
    kind: Literal["income", "expense"]
    amount_cents: Cents
    occurred_on: Day
    category_id: Id | None = None
    income_source: str | None = None
    one_off: bool = False
    note: str = ""


class Versioned(BaseModel):
    version: Id


class TransactionEdit(TransactionIn, Versioned):
    pass


class SeriesIn(BaseModel):
    name: str
    amount_cents: Cents
    category_id: Id
    freq: Literal["once", "weekly", "monthly"]
    interval: Annotated[int, Field(ge=1, le=52)] = 1
    anchor_date: Day
    until: Day | None = None
    count: Annotated[int, Field(ge=1, le=500)] | None = None


class SplitIn(SeriesIn, Versioned):
    pass


class OccurrenceEdit(Versioned):
    amount_cents: Cents
    due_date: Day


class PaymentIn(Versioned):
    paid_on: Day | None = None


class GoalIn(BaseModel):
    name: str
    target_cents: Cents
    target_date: Day | None = None
    priority: Annotated[int, Field(ge=1, le=3)] = 2
    auto_reserve: bool = False


class GoalEdit(GoalIn, Versioned):
    pass


class MovementIn(BaseModel):
    delta_cents: Cents


class LimitIn(BaseModel):
    limit_cents: Cents | None
    scope: Literal["template", "cycle"] = "template"


class NameIn(BaseModel):
    name: str


class RenameIn(NameIn, Versioned):
    pass


class CodeIn(BaseModel):
    code: str


class TransferIn(Versioned):
    new_owner_id: Id


class Participant(BaseModel):
    user_id: Id
    value: Cents | None = None


class ExpenseIn(BaseModel):
    amount_cents: Cents
    spent_on: Day
    category_id: Id
    description: str
    one_off: bool = False
    split_method: Literal["equal", "exact", "percentage", "shares"] = "equal"
    participants: list[Participant]


class ExpenseEdit(ExpenseIn, Versioned):
    pass


class SettlementIn(BaseModel):
    payer_user_id: Id
    payee_user_id: Id
    amount_cents: Cents
    paid_on: Day


class ReasonIn(Versioned):
    reason: str = ""


class HouseholdBillIn(SeriesIn):
    split_method: Literal["equal", "percentage", "shares", "exact"] = "equal"
    participants: list[Participant]
