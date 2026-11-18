"""A scripted stand-in for the households service (ADR-9: the personal service's tests stub the other side).

It answers the three calls of app.clients.households from data the test sets up, so a test can say "the
households service says Ana owes €10.00" and check what the dashboard and the alerts do with it. The real
service's answers are checked in the households service's own tests and in the cross-seam integration test.
"""

from dataclasses import dataclass, field, replace
from datetime import date

from app.clients.households import (
    EMPTY_POSITION,
    AwaitingSettlement,
    Events,
    ExpenseEvent,
    HouseholdsUnavailable,
    Position,
    Share,
)


@dataclass
class ScriptedHouseholds:
    positions: dict[int, Position] = field(default_factory=dict)
    share_rows: dict[int, list[Share]] = field(default_factory=dict)
    expense_events: list[tuple[int, ExpenseEvent]] = field(default_factory=list)  # (recipient user_id, event)
    awaiting: dict[int, list[AwaitingSettlement]] = field(default_factory=dict)
    down: bool = False
    calls: int = 0

    def _check(self) -> None:
        self.calls += 1
        if self.down:
            raise HouseholdsUnavailable("Household data is unavailable right now.")

    def position(self, user_id, *, window_end, horizon_end):
        self._check()
        position = self.positions.get(user_id, EMPTY_POSITION)
        return replace(position, commitments=tuple(c for c in position.commitments if c[0] < horizon_end))

    def shares(self, user_id, *, start, end_exclusive):
        self._check()
        return [s for s in self.share_rows.get(user_id, []) if start <= s.occurred_on < end_exclusive]

    def events(self, user_id, *, after):
        self._check()
        mine = [e for recipient, e in self.expense_events if recipient == user_id and e.audit_event_id > after]
        last = max([after] + [e.audit_event_id for _, e in self.expense_events])
        return Events(last, tuple(mine), tuple(self.awaiting.get(user_id, [])))


def share(cents: int, on: date, category_id: int, *, from_bill: bool = False, one_off: bool = False) -> Share:
    return Share(cents, on, category_id, from_bill, one_off)
