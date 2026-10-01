# Planned commits

This is the day-by-day commit schedule for building Float v0.2. It turns the scope in `PRD.md` and `SRS.md` into real, incremental work. `EXECUTION_PLAN.md` holds the task-level detail behind each commit.

Features are built from 30 September to 3 October. **4 October is reserved for testing, bug fixes, UI polish, and final checks.** See the change log at the end.

## Ground rules

1. **Build it the day it is committed.** Each commit contains work done that day. Never write code ahead and release it in later commits, and never backdate or rewrite commit dates.
2. **Commit when a piece works.** Each commit leaves the app runnable and its tests green, so any commit can be checked out and run.
3. **Push every day.** Each day ends with its branch pushed, a pull request opened, and the PR merged into `main`.
4. **Record evidence the same day.** Add the day's `AI_USAGE.md` rows and any `ADR.md` entry for a decision made that day, dated truthfully.
5. **If the plan changes, update this file.** Record what actually happened, including anything cut, and never edit history to match the plan.

## Assignment rules this schedule satisfies

| Rule | How |
|---|---|
| At least 12 meaningful commits | 2 on 28 Sep and 6 on 30 Sep, then 5–7 on each of 1–3 October and 3–6 on 4 October |
| At least 6 calendar days with pushes | 28 Sep, 30 Sep, 1 Oct, 2 Oct, 3 Oct, 4 Oct. 29 September had no commits, so **no remaining day can be skipped**, including the testing day |
| No day above 40% of the final total | See the budget below; the largest day stays near 24% |

Check the rule at any time with:

```bash
git log --date=short --format=%ad main | sort | uniq -c
```

### Commit budget

Merge commits are counted too, as the conservative reading of the rule.

| Day | Content commits | Merges | Day total | Status |
|---|---|---|---|---|
| Mon 28 Sep | 2 | 1 | 3 | done |
| Wed 30 Sep | 2 (requirements v0.2) + 3 (foundation) + 1 (this schedule change) | 3 | 9 | done |
| Thu 1 Oct | 5 | 1 | 6 | in progress |
| Fri 2 Oct | 7 | 1 | 8 | planned |
| Sat 3 Oct | 7 (6 if the API is cut) | 1 | 8 | planned |
| Sun 4 Oct | 3–6 | 1 | 4–7 | planned |
| **Total** | | | **about 38** | |

With about 38 commits, the largest day (30 Sep, 9 commits) is about 24%. Even if every remaining day manages only 3 content commits plus a merge, the total is 28 and 30 Sep is 32%, still under 40%. **No more commits on 30 September.**

## Day 0 — Wednesday 30 September: foundation

Branch `build/2026-09-30-foundation`. Requirements were merged earlier today (PR #2).

- [x] `Plan the incremental v0.2 build and daily commit schedule`: this file, `EXECUTION_PLAN.md`, and approval status in PRD/SRS/README.
- [x] `Add FastAPI skeleton with configuration and SQLite migrations`: `app.py`, app factory, `.env`-aware settings, SQLite connection pragmas, `BEGIN IMMEDIATE` unit of work, migration runner, fixed categories, health check, base template, architecture test.
- [x] `Add exact money, allowance-cycle, and recurrence rules`: integer-cent parsing and formatting, cycle dates, injectable clock, recurrence expansion with property tests, README run instructions, and AI log rows.
- [x] Merge PR `Build the Float foundation` (PR #3).
- [x] `Reserve 4 October for testing, fixes, and polish` (branch `docs/2026-09-30-replan-day4`): this schedule change.
- [x] Merge PR `Reserve 4 October for testing and polish` (PR #4), ticked in the first commit of 1 October.

Evidence: AI log rows for the planning discussion, the foundation build, and this schedule change.

## Day 1 — Thursday 1 October: Identity and Ledger (P0)

Branch `build/2026-10-01-identity-ledger`.

- [x] `Add accounts with scrypt passwords, sessions, and login throttling` (FR-01–03)
- [ ] `Protect browser requests with sessions, CSRF tokens, and security headers` (FR-04, §9, NFR-10)
- [ ] `Record ledger transactions with exact validation and an audit trail` (FR-06–08, FR-33 base)
- [ ] `Add setup, transaction pages, and the recorded-balance dashboard` (FR-05, FR-28, FR-39)
- [ ] `Record the stack and domain-boundary decisions` (ADR-1, ADR-2, AI log)
- [ ] Merge PR `Build accounts and the personal ledger`

## Day 2 — Friday 2 October: Planning, safe-to-spend, and personal insight (P0 + P1)

Branch `build/2026-10-02-planning-insight`. The first four commits are P0; the next two are P1, in priority order.

- [ ] `Materialize recurring bill occurrences idempotently` (FR-09–11)
- [ ] `Pay, undo, skip, and split bill series atomically` (FR-12–13)
- [ ] `Track savings goals with protect and release movements` (FR-14)
- [ ] `Compute safe-to-spend with breakdown, reminder, and purchase preview` (FR-27–29)
- [ ] `Forecast pace, runway, cash projection, and next-cycle outlook` (FR-30, personal data; household terms join on day 3)
- [ ] `Plan goal contributions, budgets, and unusual-expense flags` (FR-15, FR-16, FR-31)
- [ ] `Record the schema decision and log AI use` (ADR-3, AI log)
- [ ] Merge PR `Build recurring bills, goals, safe-to-spend, and the forecast`

## Day 3 — Saturday 3 October: Households, alerts, and the report draft (P0 + P1)

Branch `build/2026-10-03-households-alerts`. The first four commits are P0; the alerts and API commits are P1.

- [ ] `Create households with single-use invitations and membership rules` (FR-17–19)
- [ ] `Split shared expenses exactly with largest-remainder allocation` (FR-20–22)
- [ ] `Show household balances, settle-up plans, and confirmed settlements` (FR-23–24)
- [ ] `Reserve and pay household bills and complete the conservation tests` (FR-25–26, §4.5, household terms in the forecast)
- [ ] `Add the alert centre and household activity feed` (FR-32–33)
- [ ] `Expose the JSON API with idempotency keys` (FR-34–35), only if time remains
- [ ] `Record the testing decision, final ADR, and report draft` (ADR-4, ADR-5, report draft, AI log)
- [ ] Merge PR `Build households, alerts, and the report draft`

## Day 4 — Sunday 4 October: testing, fixes, and polish (deadline 23:59)

Branch `build/2026-10-04-verify-polish`. **No new features.** Merge by 20:00 to keep a buffer before the deadline.

- [ ] `Record the acceptance pass and performance measurements` (fresh-clone check, full suite and coverage, performance smoke test, walkthrough with the student; AT-29–31, NFR-05)
- [ ] `Fix <symptom>`: one commit per bug or small related group, each with a regression test written first
- [ ] `Improve <page or flow>`: UI changes from the student's own review
- [ ] `Record final measurements and verification results` (README numbers, report numbers, AI log, final status here)
- [ ] Merge PR `Verify, fix, and polish Float for submission`

## Cut order if a day runs late

1. P2 (FR-36–38) is not scheduled on any day and is listed as not implemented unless time is left over.
2. A P1 feature still unfinished at the end of 2 or 3 October is **cut, not moved to 4 October**. First to go is the JSON API (FR-34–35), then the alert centre and activity feed (keeping the audit table), then budgets and unusual-expense flags.
3. If a P0 feature slips, it is finished first thing on 4 October, before the acceptance pass. That is the only feature work allowed on the 4th.
4. Never cut tests, the AI log, ADRs, the README coverage result, or the report.

Anything cut is listed as "not implemented" in the README and report. Nothing is presented as done when it is not.

## Change log

- **30 September.** At the student's request, 4 October is now reserved for testing, bug fixes, UI polish, and making sure the product works as intended. Its feature work (forecast, goal plans and budgets, alerts and the activity feed, JSON API) moved to 2 and 3 October. ADR-5 and the report draft moved to 3 October. The 4th keeps only the final measurements and document updates.
