# Float — Product Requirements Document

Version: 0.2 · Date: 2026-09-30 · Status: revised proposal after professor feedback; professor approval pending.

## 1. Purpose

Float helps a student who lives on a **€750 monthly allowance** answer one question honestly: **how much can I spend today?**

Version 0.1 answered this for one person with a balance, some bills, and savings. The professor's feedback was that the idea was too thin and the backend too simple. Version 0.2 keeps that question but covers the finances of a typical student: **shared living**.

Most students who move away from home share a flat. Their bank balance is misleading for three reasons that a simple tracker misses:

1. **Recurring commitments.** Rent, phone, gym, and subscriptions fall due on different days and repeat with different rules.
2. **Money owed to flatmates.** If a flatmate paid the electricity, part of your balance is already theirs. If you paid the groceries, you are owed money you do not yet have.
3. **Goals with deadlines.** Saving €600 for a laptop by March only works if money is set aside every cycle.

Float models all three. It records what actually happened (**cash**) separately from what is committed (**obligations**). It splits and settles shared costs between flatmates and forecasts whether the current spending pace lasts until the next allowance. Every number on the dashboard can be traced back to the records behind it.

The recommendation still depends on complete, accurate records. It is a budgeting estimate, not a guarantee, and Float never connects to a bank.

## 2. What changed from v0.1

| Area | v0.1 | v0.2 |
|---|---|---|
| Users | One local user, no login | Multiple accounts with secure sessions; each user's finances are private |
| Social | None | Households (flats): invitations, shared expenses, four split methods, balances, debt simplification, two-party settlement confirmation |
| Commitments | One-off bills plus a manual "copy to next month" button | Recurrence engine (monthly/weekly/interval rules, end conditions, "this and future" edits, skips) with idempotent on-demand materialization |
| Daily number | Balance − bills − savings | Balance − personal bills − your share of household bills − protected savings − what you owe flatmates − planned goal contributions |
| Goals | Target plus manually protected amount | Target dates, priorities, and a per-cycle contribution plan that is reserved automatically on request |
| Insight | Category totals and limits | Spending pace, runway and run-out date, next-cycle outlook, cash forecast, anomaly detection, budget templates, and an alert centre |
| Backend | Two domains, one coordinator | Three domains (Ledger, Planning, Households) plus Identity and Insights modules, multi-user authorization, atomic cross-domain workflows, optimistic concurrency, idempotency keys, an audit trail, and a versioned JSON API |
| Data entry | Manual only | Manual, with optional bank-statement CSV import and duplicate detection (stretch) |

## 3. Confirmed input and proposed defaults

| Topic | Confirmed by the student | Proposed implementation detail |
|---|---|---|
| Income | Monthly allowance of €750 | Default planned allowance €750. Receipt must still be recorded; Float never invents income |
| Primary need | What can I spend today until the next allowance? | Safe-to-spend formula in SRS §4.5, with every term shown on the dashboard |
| Secondary needs | Category analysis and purchase/trip affordability | Consumption-based category insight, what-if preview, pace and forecast |
| Coverage | Bills, savings, and everyday spending ("everything") | Extended to shared flat costs because they change what the student can safely spend |
| Entry | Manual | Manual forms remain primary; CSV import is a P2 stretch goal |
| Stack | Python/FastAPI | FastAPI, SQLite through Python's `sqlite3`, Jinja2 templates, light CSS/JavaScript, and a JSON API from the same process |
| Professor feedback | Idea too weak; backend should be more complex | Households, recurrence, forecasting, multi-user security, and consistency guarantees (this document) |
| Allowance date | Not specified | Chosen during setup, day 1–31; default 1; short months clamp to their last day |
| Currency | € allowance | EUR only |

Proposed defaults are engineering choices, not facts about the student's finances. Real bills, flatmates, goals, and balances are entered by users. Do not invent or prepopulate real financial records. The household scope is a proposal responding to the professor's feedback; it is not something the student originally requested.

## 4. Users and stakeholders

- **Student (primary user):** manages a fixed allowance and wants a quick, trustworthy daily spending decision.
- **Flatmate (household member):** shares rent, utilities, and groceries. Records the shared costs they pay and confirms settlements they receive.
- **Household owner:** the flatmate who created the household. Invites and removes members and manages shared recurring bills.
- **Developer:** the student, responsible for understanding and explaining all submitted code and decisions.
- **Academic reviewer:** the professor, who approves scope and evaluates modularity, testing, process evidence, and comprehension.

Float runs as one instance on one machine that flatmates reach over a trusted home network, for example a laptop in the flat. It is not a public web service.

## 5. Product principles

These rules settle design questions throughout the SRS.

1. **Cash is what happened; obligations are what is committed.** The Ledger records only real money movements. Bills, shares, debts, and goal plans are obligations that reserve cash without moving it.
2. **Count what you owe, not what you are owed.** Money a flatmate owes you increases safe-to-spend only after the settlement is confirmed. Planned allowance works the same way: it counts only once received.
3. **Conservation.** When an obligation becomes a payment (paying a bill, confirming a settlement, protecting planned goal money), cash and reservations change by the same amount, so safe-to-spend does not change. It changes only when money owed to you changes, for example when you pay a shared bill for everyone, and that money counts once it is settled. Automated tests enforce this invariant.
4. **Never invent money or events.** Float does not auto-post allowance, auto-pay bills, or move money between people. Recurring commitments are scheduled; realizing them is always a user action.
5. **Explain every number.** Each dashboard figure links to the records and formula terms that produced it.
6. **Your data is yours.** Personal transactions, goals, and bills are private. Household members see only household records and the balances between them.

## 6. Product experience

### Onboarding

A new visitor creates an account with a username and password. Setup then asks for the tracking start date, current balance, allowance day, and planned allowance (default €750). The opening balance is money already held, so an allowance already included in it must not be entered again.

The user adds recurring commitments (rent, phone, gym) and savings goals, then either creates a household or joins one with an invitation code. Every step can be skipped. The dashboard explains that missing commitments make the estimate too optimistic.

### Daily use: the primary journey

1. Open the dashboard and see **safe to spend today**, days until the next allowance, and a pace indicator ("you're spending €12/day; safe is €28/day").
2. Expand the breakdown: recorded balance, personal bills, household bill shares, protected savings, money owed to flatmates, and planned goal contributions.
3. Record an expense or income. If the expense was shared, record it once and choose who it was split with.
4. See the updated number, category totals, and any new alerts immediately.

Planned allowance and received money stay separate. On payday Float shows a reminder to record the allowance but never assumes it arrived.

### Recurring bills

A bill is defined once with a rule: monthly on day N, every N weeks on a weekday, or once. It can have an end date or occurrence count. Float generates occurrences on demand and reserves every unpaid occurrence due before the next allowance, including overdue ones. Paying an occurrence creates one linked expense and releases its reservation in one step.

An occurrence can be skipped (no gym this month). An amount can change for one occurrence only or for "this and all future" ones. Changing future occurrences never rewrites paid history.

### Living with flatmates

The household owner invites flatmates with a single-use code that expires after 72 hours. Members record shared expenses they paid and choose a split: **equal**, **exact amounts**, **percentages**, or **shares** (for example 2:1:1 for a couple sharing a room). Splits always add up to the exact cent through a deterministic remainder rule.

Shared recurring bills (rent, internet, electricity) belong to the household. Each member's share is reserved in their own safe-to-spend before anyone pays. When one member pays the actual amount, the other members' reservations become debts to that member automatically. Safe-to-spend changes only where money owed to someone changes: the payer's falls by whatever they are now owed, until it is settled.

The household page shows each member's net balance and a **settle-up plan** that simplifies all debts into at most one fewer transfer than there are members. A settlement is recorded by either party and takes effect only when the other party confirms. Confirmation writes the matching income and expense into both personal ledgers atomically. Every change is visible in the household activity feed.

### Goals

A goal has a target amount and, optionally, a target date and priority. With a date, Float calculates how much to set aside this cycle (for example €600 by March → €100 per cycle). With auto-reserve on, that amount is held back from safe-to-spend until the user protects it. Protecting planned money therefore does not change safe-to-spend; protecting more than planned lowers it.

### Understanding spending

Category insight uses **consumption**, not cash. When you pay €30 of shared groceries, your groceries spending is your €10 share, not €30. Budget limits can be set per cycle or as templates that apply to every cycle. Float flags unusually large expenses compared with your history in the same category.

The forecast answers "will I make it?". It projects runway and a run-out date at the current pace, shows a day-by-day cash projection with and without expected income, and gives a next-cycle outlook ("after rent and bills, October leaves about €25.61/day"). A purchase or trip preview shows before/after numbers without saving anything.

### Alerts

An in-app alert centre reports bills due within three days, overdue bills, budgets at 80% and 100%, a pace that runs out before payday, an unusual expense, a settlement waiting for your confirmation, a household expense that involves you, and an unrecorded allowance. Alerts resolve themselves when the underlying condition clears.

## 7. Scope and priority

| Priority | Capability | Required outcome |
|---|---|---|
| P0 | Identity and access | Registration, login/logout, hashed passwords, expiring server-side sessions, CSRF protection, per-user data isolation, login throttling |
| P0 | Manual ledger | Record, view, edit, and delete income/expenses with exact EUR arithmetic; private per user |
| P0 | Recurrence engine and bills | Rule expansion, idempotent materialization, skip, "this and future" edits, atomic pay/undo |
| P0 | Savings goals | Protect/release movements without changing cash |
| P0 | Households and splitting | Create/join/leave, invitations, shared expenses with four split methods, net balances |
| P0 | Settlements | Debt simplification, pending → confirmed/rejected/cancelled lifecycle, atomic two-ledger confirmation |
| P0 | Household bills | Recurring shared bills whose unpaid shares are reserved per member; paying one creates the shared expense |
| P0 | Safe-to-spend v2 | Full formula with breakdown, shortfall display, and purchase/trip preview |
| P1 | Goal contribution plan | Target dates, per-cycle plan, auto-reserve, priority ordering |
| P1 | Forecast and pace | Pace, runway, run-out date, cash projection, next-cycle outlook |
| P1 | Consumption insight and budgets | Share-based category totals, per-cycle limits, budget templates, anomaly flags |
| P1 | Alerts and audit trail | Rule-based alert centre with auto-resolution; append-only audit log and household activity feed |
| P1 | JSON API | Versioned `/api/v1` with OpenAPI docs, problem-details errors, and idempotency keys for money-creating requests |
| P2 | CSV import | Statement upload, column mapping, duplicate detection, atomic import and batch undo |
| P2 | Categorization and cycle review | Suggested categories from rules/history; end-of-cycle review with a suggested sweep of leftover money into goals |

P0 precedes P1, and P1 precedes P2. Tests and documentation for a finished priority come before starting the next one. Unfinished capabilities are reported as not done rather than implemented superficially.

## 8. Backend architecture overview

Float stays a **modular monolith**: one FastAPI process and one SQLite file, with strict module boundaries that would allow later extraction into services.

| Module | Kind | Owns |
|---|---|---|
| **Ledger** | Domain | Actual income/expense transactions, categories, opening balance, statement imports |
| **Planning** | Domain | Allowance settings, recurring bill series and occurrences, savings goals and movements, budgets |
| **Households** | Domain | Households, memberships, invitations, shared expenses and splits, household bills, settlements |
| **Identity** | Supporting | Users, password hashes, sessions, login throttling |
| **Insights** | Read model | Safe-to-spend composition, forecast, pace, anomalies; persists only alerts and alert cursors |
| **Application** | Coordination | Cross-domain atomic workflows, authorization checks, audit trail, idempotency keys |

Domains never read each other's tables. They exchange data through narrow Python interfaces (snapshots and commands). The application layer runs cross-domain writes in one database transaction: paying a bill, recording a shared expense you paid, paying a household bill, and confirming a settlement.

The backend has several non-trivial parts, each specified exactly in the SRS so it can be tested:

- **Algorithms:** calendar-aware recurrence expansion with month-end clamping; largest-remainder cent allocation; greedy debt simplification with an n − 1 transfer bound; moving-window pace and runway; median/MAD anomaly detection; goal contribution planning.
- **Consistency:** atomic multi-domain transactions, the conservation invariant, optimistic concurrency with row versions for shared records, idempotent state transitions, and API idempotency keys.
- **Security:** scrypt password hashing, hashed session tokens with idle and absolute expiry, CSRF tokens, login throttling, membership-based authorization, and an append-only audit log.

## 9. Explicit exclusions

- Bank connections, open-banking APIs, receipt scanning, AI-generated advice, live exchange rates, and multiple currencies.
- Real money movement between users. Settlements record transfers that happened elsewhere, such as Bizum or bank transfer.
- Email, SMS, or push notifications. Alerts are in-app only.
- Account deletion, password-reset email, OAuth/social login, two-factor authentication, and administrator roles.
- Automatic allowance posting, automatic bill payment, and partial bill payments.
- Investments, loans, tax, and long-range (multi-month) financial planning beyond the next-cycle outlook.
- Separate frontend/backend processes, microservices, managed databases, background workers or schedulers, Docker/CI/IaC authored for this assignment, TLS termination, and public deployment.

## 10. Product acceptance goals

By the 4 October 2026 deadline:

1. A new user can register, complete setup, and record an expense in a short manual usability check, with a target of under two minutes.
2. Two users in one household can record a shared expense, see matching balances, and complete a confirmed settlement in under three minutes.
3. All three domains and Identity persist in SQLite and retain records after a restart.
4. Every numeric fixture and boundary case in the SRS passes automated tests. Property-based tests show that splits always sum exactly and household balances always sum to zero. Core logic reaches at least 70% measured line coverage.
5. No dashboard number double-counts money: the conservation tests pass for bill payment, household bill payment, settlement confirmation, and goal protection.
6. No user can read or change another user's private records through any HTML or API route (authorization tests).
7. Clone + dependency installation + one documented start command produces a ready app without interactive startup steps.
8. The README, five-entry ADR log, AI log, diagrams, and 4–5-page report describe the implementation accurately.

These are targets, not achieved results. Record actual test results and usability observations during implementation.

## 11. Delivery plan and risks

Work in thin vertical increments with tests in each: requirements v0.2 (30 Sep) → Identity + Ledger + database infrastructure (1 Oct) → Planning with the recurrence engine and safe-to-spend (2 Oct) → Households, splits, and settlements (3 Oct) → P1 insights, documentation, and verification (4 Oct). No commits were made on 29 September, so every remaining day through 4 October needs meaningful pushed work to reach the six-day minimum. Record departures from this plan in the final SDLC report.

| Risk | Response |
|---|---|
| Scope is now much larger than six days allow | Strict P0 → P1 → P2 ordering; P2 is explicitly optional; report unfinished items honestly |
| Multi-user rules add security bugs | Centralized authorization in the application layer; an authorization test for every route family |
| Shared-cost rules confuse users | Every balance links to the expenses and settlements behind it; settle-up plan in plain language |
| Rounding differences between flatmates | Integer cents and a deterministic largest-remainder rule; property-based tests |
| Concurrent edits by flatmates | Row versions with conflict messages; SQLite WAL mode and immediate write transactions |
| Manual records are incomplete | Label all figures as "recorded", show assumptions, remind users about unrecorded allowance |
| AI-generated logic is not understood | The student explains each accepted implementation in the AI log and practices the calculations without notes |
| Decisions appear retrospectively | Log ADR entries as choices are made, across at least three commit dates |

The assignment requires approval of this use case before implementation. This revised proposal responds to the professor's feedback; it does not claim that approval has happened.
