# Float — Product Requirements Document

Version: 0.1 · Date: 2026-09-28 · Status: proposed implementation baseline; professor approval pending.

## 1. Purpose

Float helps a student living on a **€750 monthly allowance** decide what they can spend today without consuming money reserved for bills and savings. It also explains where money went and previews whether a purchase or trip fits the current allowance cycle.

A bank balance alone cannot answer this: part of that balance may already be needed for rent, a subscription, or a savings goal. Float makes those commitments visible and calculates a daily discretionary allowance from the remaining recorded funds.

The recommendation is conditional on complete, accurate manual records. It is a budgeting estimate, not a guarantee or a connection to the user's bank.

## 2. Confirmed input and proposed defaults

| Topic | Confirmed by the student | Proposed implementation detail |
|---|---|---|
| Income | Monthly allowance of €750 | Default planned allowance €750; receipt must be recorded manually |
| Primary need | What can I spend today until the next allowance? | Balance minus relevant unpaid bills and protected savings, divided by days remaining |
| Secondary needs | Category analysis and purchase/trip affordability | Cycle category totals/limits and a what-if calculator |
| Coverage | Bills, savings, and everyday spending ("everything") | Bounded to the features below; no banking or investment platform |
| Entry | Manual | Simple forms; no imports or integrations |
| Stack | Python/FastAPI | SQLite, Python's `sqlite3`, Jinja2 templates, light CSS/JavaScript |
| Allowance date | Not specified | User chooses day 1–31 during setup; default 1, shortened months clamp to their last day |
| Currency/users | € allowance; no shared-user requirement | EUR only; one local user, no authentication |

Proposed defaults are engineering choices, not facts about the student's finances. Actual bills, savings targets, and opening balance are entered by the user; do not invent them or prepopulate real financial records. The following specification is ready for review, not evidence that every assumption has been personally validated.

## 3. Users and stakeholders

- Primary user: a student managing a fixed monthly allowance and wanting a quick daily spending decision.
- Developer: the student, responsible for understanding and explaining all submitted code and decisions.
- Academic reviewer: the professor, who approves the scope and evaluates modularity, testing, process evidence, and comprehension.

One person uses one local instance. Multiple users and shared households are outside this version.

## 4. Product experience

### First use

The app starts successfully before any financial setup. A browser form asks for the tracking start date, current available balance, allowance day, and planned allowance amount (default €750). The opening balance is money already held; the user must not enter the same allowance again if it is included in that balance.

The user then enters upcoming bills, any amounts already earmarked for savings, and optional category budgets. They can begin with zero bills and zero protected savings. The interface explains that missing commitments make the estimate too optimistic.

### Daily use: the primary journey

1. Open the dashboard and see today's suggested discretionary spending and days until the next allowance date.
2. Inspect the calculation: recorded balance, unpaid bills, protected savings, and discretionary funds.
3. Record an expense or received income manually.
4. See the updated daily amount and category breakdown immediately.

The dashboard must distinguish **planned allowance** from **received money**. Reaching payday must never create income automatically. An unrecorded new allowance displays a reminder, while calculations continue using only existing recorded funds.

### Bills and savings

Bills have names, amounts, and due dates. Float reserves unpaid bills due before the next allowance date, including overdue bills. Marking a bill paid creates one linked expense and releases that bill's reservation in the same operation.

Savings goals have a target and a manually protected amount. Protected money remains within the recorded balance but is excluded from daily spending; it is not a second expense or a bank transfer.

Monthly bills can be copied into the next cycle with a button. There is no unattended recurrence or background scheduler. One-off bills are entered directly; future commitments are visible before they enter the current calculation.

### Understand spending and try a purchase

The user can compare current-cycle spending by category with optional category limits. Bills count as expenses when paid. Limits provide warnings; they do not reserve cash a second time or block expense entry.

For a purchase or trip, the user enters a total expected cost and sees remaining discretionary funds and the revised daily amount. This is a current-cycle simulation only; it does not post an expense. It clearly states that protected savings stay reserved.

## 5. Scope and priority

| Priority | Capability | Required outcome |
|---|---|---|
| P0 | Manual ledger | Record, view, edit, and delete ordinary income/expenses with reliable EUR arithmetic |
| P0 | Daily spending estimate | Explain the calculation and display a shortfall when commitments exceed cash |
| P0 | Bills | Create/edit unpaid bills, pay/undo payment atomically, retain overdue reservations |
| P0 | Savings | Create goals and change protected amounts without changing ledger cash |
| P1 | Spending insight | Cycle totals per category, optional limits, overspending warnings |
| P1 | Purchase/trip preview | Show the before/after daily allowance without mutating finances |
| P1 | Monthly bill convenience | Copy a bill to the next cycle safely without duplicate occurrences |

All listed capabilities are in the target submission. P0 precedes P1 during development; do not replace test coverage and documentation with extra polish.

## 6. Two backend domains

**Ledger** owns categories, opening balance, and actual income/expense records. It validates and persists actual money movements and exposes balance and category totals.

**Planning** owns allowance settings, bill commitments, savings goals, and category limits. It persists those records and calculates daily allowances and hypothetical purchase outcomes using values supplied through the Ledger interface.

The domains run in one process and share one SQLite file. Planning must not reach into Ledger's tables for its calculations. A small application coordinator handles the one cross-domain write: paying or undoing a bill payment. The SRS specifies the boundary and its consistency tradeoff.

## 7. Explicit exclusions

- Bank connections, CSV imports, receipt scanning, AI-generated advice, live exchange rates, and multiple currencies.
- Login, multiple accounts/users, shared-expense settlement, lending, investments, or tax calculations.
- Automatic allowance deposits, automatic bill payments, partial bill payments, and variable/weekly recurrence.
- Long-range financial forecasting, saved scenario history, or guarantees that a purchase is financially safe.
- Separate frontend/backend processes, microservices, managed databases, background workers, Docker/CI/IaC authored for this assignment, and public deployment.

## 8. Product acceptance goals

By the 4 October 2026 deadline:

1. A new user can complete setup and record an expense in a short manual usability check, with a target of under two minutes.
2. Both domains read/write SQLite and retain records after restarting the process.
3. The SRS's numeric examples and boundary cases pass automated tests; core business logic reaches at least 70% measured coverage.
4. Every dashboard recommendation exposes the numbers behind it, and no forecast or bill action double-counts money.
5. Clone + dependency installation + one documented start command produces a ready local app without interactive startup steps.
6. The README, five-entry ADR log, AI log, diagrams, and 4–5-page report describe the implementation accurately.

These are targets, not achieved results. Record actual test results and usability observations during implementation.

## 9. Delivery and risks

Use small iterative increments: requirements → Ledger with tests → Planning with tests → interface/integration → documentation and verification. This fits a short deadline and provides decisions and working evidence across days. Record departures from this plan in the final SDLC report.

| Risk | Response |
|---|---|
| Manual records are incomplete | Label balance as recorded balance and display the calculation assumptions |
| Too much scope for six days | Prioritize the two domains and core rules; keep forms and charts simple |
| Allowance is late | Never invent a receipt; remind the user to record it and show the next scheduled date explicitly |
| AI-generated logic is not understood | Student explains each accepted implementation in the log and practices calculations without notes |
| Decisions appear retrospectively | Finalize and log ADR entries as choices are actually made across at least three commit dates |

The assignment requires approval of this use case before application implementation. This documentation does not claim that approval has happened.
