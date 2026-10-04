"""Pure ledger rules: what a valid transaction and a valid setup look like (FR-05–08, SRS §2)."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from app.shared.errors import ValidationError
from app.shared.money import MAX_CENTS

KINDS = ("income", "expense")
INCOME_SOURCES = ("allowance", "settlement", "other")
MANUAL_INCOME_SOURCES = ("allowance", "other")  # settlement income only comes from the settlement workflow
ORIGINS = ("manual", "bill", "shared", "settlement", "import")
LINKED_ORIGINS = ("bill", "shared", "settlement")
DIRECTLY_EDITABLE = frozenset({"manual", "import"})
NOTE_LIMIT = 500


@dataclass(frozen=True)
class TransactionDraft:
    kind: str
    amount_cents: int
    occurred_on: date
    category_id: int | None = None
    income_source: str | None = None
    one_off: bool = False
    note: str = ""


def validate_occurred_on(occurred_on: date, *, tracking_start: date, today: date) -> None:
    if occurred_on > today:
        raise ValidationError.single("occurred_on", "Future transactions cannot be recorded yet.")
    if occurred_on < tracking_start:
        raise ValidationError.single(
            "occurred_on", f"Choose a date on or after {tracking_start.isoformat()}, when tracking started."
        )


def validate_draft(draft: TransactionDraft, *, tracking_start: date, today: date,
                   category_ids: Collection[int]) -> None:
    errors: dict[str, str] = {}
    if draft.kind not in KINDS:
        errors["kind"] = "Choose income or expense."
    if not 1 <= draft.amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    try:
        validate_occurred_on(draft.occurred_on, tracking_start=tracking_start, today=today)
    except ValidationError as error:
        errors.update(error.errors)
    if draft.kind == "expense":
        if draft.category_id not in category_ids:
            errors["category_id"] = "Choose a category."
        if draft.income_source is not None:
            errors["income_source"] = "Expenses have no income source."
    elif draft.kind == "income":
        if draft.income_source not in MANUAL_INCOME_SOURCES:
            errors["income_source"] = "Choose allowance or other income."
        if draft.category_id is not None:
            errors["category_id"] = "Income has no category."
        if draft.one_off:
            errors["one_off"] = "Only expenses can be marked one-off."
    if len(draft.note) > NOTE_LIMIT:
        errors["note"] = "Keep notes to 500 characters."
    if errors:
        raise ValidationError(errors)


def validate_settings(*, tracking_start: date, opening_balance_cents: int, today: date) -> None:
    errors: dict[str, str] = {}
    if tracking_start > today:
        errors["tracking_start"] = "Tracking cannot start in the future."
    if abs(opening_balance_cents) > MAX_CENTS:
        errors["opening_balance"] = "Amounts are limited to €1,000,000.00."
    if errors:
        raise ValidationError(errors)


# Words that point to each fixed category, for automatic categorization from what the user typed.
CATEGORY_KEYWORDS = {
    "groceries": ("grocer", "supermarket", "mercadona", "lidl", "aldi", "carrefour", "dia ", "market", "shop",
                  "food", "fruit", "vegetable", "milk", "bread", "eggs"),
    "eating_out": ("restaurant", "pizza", "burger", "sushi", "ramen", "kebab", "cafe", "coffee", "lunch", "dinner",
                   "breakfast", "bar ", "drinks", "takeaway", "delivery", "glovo", "uber eats", "mcdonald", "taco"),
    "transport": ("metro", "bus", "train", "taxi", "uber", "cabify", "fuel", "petrol", "parking", "bike", "transport"),
    "housing": ("rent", "deposit", "landlord", "furniture", "ikea", "housing"),
    "utilities": ("electric", "water", "gas", "internet", "wifi", "phone", "mobile", "utility", "utilities", "power"),
    "subscriptions": ("netflix", "spotify", "subscription", "prime", "disney", "hbo", "icloud", "gym", "membership",
                      "youtube", "chatgpt"),
    "study": ("book", "course", "tuition", "university", "uni ", "library", "stationery", "laptop", "printing",
              "exam", "study"),
    "leisure": ("cinema", "movie", "concert", "game", "party", "club", "museum", "festival", "theatre", "bowling",
                "sport"),
    "health": ("pharmacy", "doctor", "dentist", "medicine", "hospital", "health", "clinic", "glasses", "therapy"),
    "travel": ("flight", "hotel", "airbnb", "hostel", "trip", "travel", "holiday", "ryanair", "vueling", "booking"),
}


def suggest_category(text: str, categories) -> int:
    """The category that best matches ``text``: the user's own category names first, then keywords, else Other."""
    lowered = f" {(text or '').lower()} "
    for category in categories:
        if getattr(category, "custom", False) and category.name.lower() in lowered:
            return category.id
    by_slug = {category.slug: category.id for category in categories}
    for slug, words in CATEGORY_KEYWORDS.items():
        if slug in by_slug and any(word in lowered for word in words):
            return by_slug[slug]
    return by_slug.get("other", next(iter(by_slug.values())))
