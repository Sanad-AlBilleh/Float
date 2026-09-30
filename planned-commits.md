# Planned commits

This is the day-by-day commit schedule for building Float v0.2. It turns the scope in `PRD.md` and `SRS.md` into real, incremental work. `EXECUTION_PLAN.md` holds the task-level detail behind each commit.

## Ground rules

1. **Build it the day it is committed.** Each commit contains work done that day. Never write code ahead and release it in later commits, and never backdate or rewrite commit dates.
2. **Commit when a piece works.** Each commit leaves the app runnable and its tests green, so any commit can be checked out and run.
3. **Push every day.** Each day ends with its branch pushed, a pull request opened, and the PR merged into `main`.
4. **Record evidence the same day.** Add the day's `AI_USAGE.md` rows and any `ADR.md` entry for a decision made that day, dated truthfully.
5. **If the plan changes, update this file.** Record what actually happened, including anything cut, and never edit history to match the plan.

## Assignment rules this schedule satisfies

| Rule | How |
|---|---|
| At least 12 meaningful commits | 2 on 28 Sep, 5 on 30 Sep, then about 4–5 on each of 1–4 October |
| At least 6 calendar days with pushes | 28 Sep, 30 Sep, 1 Oct, 2 Oct, 3 Oct, 4 Oct. 29 September had no commits, so **no remaining day can be skipped** |
| No day above 40% of the final total | See the budget below; the largest day stays near 20–25% |

Check the rule at any time with:

```bash
git log --date=short --format=%ad main | sort | uniq -c
```

### Commit budget

Merge commits are counted too, as the conservative reading of the rule.

| Day | Content commits | Merge | Day total | Status |
|---|---|---|---|---|
| Mon 28 Sep | 2 | 1 | 3 | done |
| Wed 30 Sep | 2 (requirements v0.2) + 3 (foundation build) | 2 | 7 | in progress |
| Thu 1 Oct | 5 | 1 | 6 | planned |
| Fri 2 Oct | 5 | 1 | 6 | planned |
| Sat 3 Oct | 5 | 1 | 6 | planned |
| Sun 4 Oct | 5 | 1 | 6 | planned |
| **Total** | | | **34** | |

With 34 commits, the largest day (30 Sep) is 7/34 ≈ 21%. Even if every remaining day manages only 3 content commits plus a merge, the total is 26 and 30 Sep is 27%, still under 40%. **Do not add more commits to 30 September** beyond the ones listed below.

## Day 0 — Wednesday 30 September: foundation

Branch `build/2026-09-30-foundation`. Requirements were merged earlier today (PR #2).

- [x] `Plan the incremental v0.2 build and daily commit schedule`: this file, `EXECUTION_PLAN.md`, and approval status in PRD/SRS/README.
- [x] `Add FastAPI skeleton with configuration and SQLite migrations`: `app.py`, app factory, `.env`-aware settings, SQLite connection pragmas, `BEGIN IMMEDIATE` unit of work, migration runner, fixed categories, health check, base template, architecture test.
- [x] `Add exact money, allowance-cycle, and recurrence rules`: integer-cent parsing and formatting, cycle dates, injectable clock, recurrence expansion with property tests, README run instructions, and AI log rows.
- [ ] Merge PR `Build the Float foundation`. (This box is ticked in the next day's first commit, so 30 September gets no extra commit.)

Evidence: AI log rows for the planning discussion and the foundation build.

## Day 1 — Thursday 1 October: Identity and Ledger (P0)

Branch `build/2026-10-01-identity-ledger`.

- [ ] `Add accounts with scrypt passwords, sessions, and login throttling` (FR-01–03)
- [ ] `Protect browser requests with sessions, CSRF tokens, and security headers` (FR-04, §9, NFR-10)
- [ ] `Record ledger transactions with exact validation and an audit trail` (FR-06–08, FR-33 base)
- [ ] `Add setup, transaction pages, and the recorded-balance dashboard` (FR-05, FR-39)
- [ ] `Record the stack and domain-boundary decisions` (ADR-1, ADR-2, AI log)
- [ ] Merge PR `Build accounts and the personal ledger`

## Day 2 — Friday 2 October: Planning and safe-to-spend (P0)

Branch `build/2026-10-02-planning`.

- [ ] `Materialize recurring bill occurrences idempotently` (FR-09–11)
- [ ] `Pay, undo, skip, and split bill series atomically` (FR-12–13)
- [ ] `Track savings goals with protect and release movements` (FR-14)
- [ ] `Compute safe-to-spend with breakdown, reminder, and purchase preview` (FR-27–29, personal terms)
- [ ] `Record the schema decision and log AI use` (ADR-3, AI log)
- [ ] Merge PR `Build recurring bills, goals, and safe-to-spend`

## Day 3 — Saturday 3 October: Households (P0)

Branch `build/2026-10-03-households`.

- [ ] `Create households with single-use invitations and membership rules` (FR-17–19)
- [ ] `Split shared expenses exactly with largest-remainder allocation` (FR-20–22)
- [ ] `Show household balances, settle-up plans, and confirmed settlements` (FR-23–24)
- [ ] `Reserve and pay household bills and complete the conservation tests` (FR-25–26, §4.5)
- [ ] `Record the testing decision and log AI use` (ADR-4, AI log)
- [ ] Merge PR `Build households, splits, and settlements`

## Day 4 — Sunday 4 October: P1 insight and submission (deadline 23:59)

Branch `build/2026-10-04-insights-release`. Stop feature work by 19:00 and spend the rest of the evening on documentation and verification.

- [ ] `Forecast pace, runway, cash projection, and next-cycle outlook` (FR-30)
- [ ] `Plan goal contributions, budgets, and unusual-expense flags` (FR-15, FR-16, FR-31)
- [ ] `Add the alert centre and household activity feed` (FR-32, FR-33)
- [ ] `Expose the JSON API with idempotency keys` (FR-34–35), only if time remains
- [ ] `Document setup, coverage, measurements, and final decisions` (README, ADR-5, report, AI log)
- [ ] Merge PR `Add insight features and submission documents`

## Cut order if a day runs late

1. Drop P2 entirely (FR-36–38). It is optional by design.
2. Drop the JSON API (FR-34–35) and report it as not implemented.
3. Drop the alert centre and activity feed (FR-32–33 UI), keeping the audit table.
4. Move household bills (FR-25–26) to the morning of 4 October, ahead of any P1 work.
5. Never cut tests, the AI log, ADRs, the README coverage result, or the report.

Anything cut is listed as "not implemented" in the README and report. Nothing is presented as done when it is not.
