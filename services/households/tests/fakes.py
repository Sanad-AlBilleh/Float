"""An in-memory stand-in for the personal service (ADR-9: each service's tests stub the other side).

It keeps users, their profiles and the ledger rows this service asks it to create, and applies the same
ledger rules that matter here (the date must be inside the payer's tracking and not in the future; a
shared expense must use one of the payer's categories). ``down = True`` makes every call fail as a
timeout would, to test the designed partial failure. The real endpoints are tested in the personal
service, and both together in the cross-seam integration test.
"""

from dataclasses import dataclass, field
from datetime import date

from app.clients.personal import PersonalUnavailable, Profile
from app.shared.errors import ConflictError, NotFoundError, ValidationError

FIXED_CATEGORIES = frozenset(range(1, 12))


@dataclass
class LedgerRow:
    id: int
    user_id: int
    kind: str
    origin: str
    amount_cents: int
    occurred_on: date
    category_id: int | None
    income_source: str | None
    note: str


@dataclass
class FakePersonal:
    today: date = date(2026, 9, 30)
    profiles: dict[int, Profile] = field(default_factory=dict)
    rows: dict[int, LedgerRow] = field(default_factory=dict)
    keys: dict[str, int] = field(default_factory=dict)
    down: bool = False
    fail_after_creates: int | None = None  # make the n-th create (1-based) fail, to test compensation
    creates: int = 0

    def _check(self) -> None:
        if self.down:
            raise PersonalUnavailable()

    def add_user(self, user_id: int, name: str, *, tracking_start: date | None = None, allowance_day: int = 1,
                 extra_categories: frozenset[int] = frozenset()) -> None:
        self.profiles[user_id] = Profile(user_id, name, tracking_start is not None, tracking_start, allowance_day,
                                         FIXED_CATEGORIES | extra_categories)

    def names(self, user_ids) -> dict[int, str]:
        self._check()
        return {i: self.profiles[i].display_name for i in user_ids if i in self.profiles}

    def profile(self, user_id: int) -> Profile:
        self._check()
        if user_id not in self.profiles:
            raise NotFoundError("No such user.")
        return self.profiles[user_id]

    def _validate(self, user_id: int, occurred_on: date) -> None:
        start = self.profile(user_id).tracking_start
        if start is None:
            raise ConflictError("Complete setup first.")
        if occurred_on < start or occurred_on > self.today:
            raise ValidationError.single("occurred_on", "Choose a date inside your tracking.")

    def create_transaction(self, *, user_id, kind, origin, amount_cents, occurred_on, category_id, income_source,
                           note, key) -> int:
        self._check()
        if key in self.keys:
            return self.keys[key]
        self.creates += 1
        if self.fail_after_creates is not None and self.creates >= self.fail_after_creates:
            raise PersonalUnavailable()
        self._validate(user_id, occurred_on)
        if origin == "shared" and category_id not in self.profile(user_id).category_ids:
            raise ValidationError.single("category_id", "Choose one of the listed categories.")
        row_id = max(self.rows, default=0) + 1
        self.rows[row_id] = LedgerRow(row_id, user_id, kind, origin, amount_cents, occurred_on, category_id,
                                      income_source, note)
        self.keys[key] = row_id
        return row_id

    def _linked(self, transaction_id: int, user_id: int, origin: str) -> LedgerRow:
        row = self.rows.get(transaction_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError("No such record in the ledger.")
        if row.origin != origin:
            raise ConflictError("Not a linked transaction.")
        return row

    def update_transaction(self, transaction_id, *, user_id, origin, amount_cents, occurred_on, category_id) -> None:
        self._check()
        row = self._linked(transaction_id, user_id, origin)
        self._validate(user_id, occurred_on)
        row.amount_cents, row.occurred_on, row.category_id = amount_cents, occurred_on, category_id

    def delete_transaction(self, transaction_id, *, user_id, origin) -> None:
        self._check()
        self._linked(transaction_id, user_id, origin)
        del self.rows[transaction_id]

    def ledger(self, user_id: int, origin: str | None = None) -> list[LedgerRow]:
        return [r for r in self.rows.values() if r.user_id == user_id and (origin is None or r.origin == origin)]
