# Planned commits

This is the day-by-day commit schedule for building Float v0.2. It turns the scope in `PRD.md` and `SRS.md` into real, incremental work. `EXECUTION_PLAN.md` holds the task-level detail behind each commit.

Features are built from 30 September to 3 October. **4 October is reserved for testing, bug fixes, UI polish, and final checks.** See the change log at the end.

## Ground rules

1. **Build it the day it is committed.** Each commit contains work done that day. Never write code ahead and release it in later commits, and never backdate or rewrite commit dates.
2. **Commit when a piece works.** Each commit leaves the app runnable and its tests green, so any commit can be checked out and run.
3. **Push every day.** Each day ends with its branch pushed, a pull request opened, and the PR merged into `main`.
4. **Record evidence the same day.** Add the day's `AI_USAGE.md` rows and any `ADR.md` entry for a decision made that day, dated truthfully.
5. **If the plan changes, update this file.** Record what actually happened, including anything cut, and never edit history to match the plan.

Branches are named for what they contain: `docs/…` for documents, `feature/…` for a build day, `fix/…` for bug fixes, and `release/…` for the final testing day. Commit dates, not branch names, record when the work happened.

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
| Thu 1 Oct | 6 (one unplanned fix) + 1 (branch renames) + 1 (review fixes) | 3 | 11 | done |
| Fri 2 Oct | 7 | 1 | 8 | done |
| Sat 3 Oct | 7 (6 if the API is cut) | 1 | 8 | in progress |
| Sun 4 Oct | 3–6 | 1 | 4–7 | planned |
| **Total** | | | **about 43** | |

With about 43 commits, the largest day (1 Oct, 11 commits) is about 26%. Even if every remaining day from 2 October manages only 3 content commits plus a merge, the total is 35 and 1 Oct is 31%, still under 40%. **No more commits on 1 October.** **No more commits on 30 September.**

## Day 0 — Wednesday 30 September: foundation

Branch `feature/project-foundation`. Requirements were merged earlier today (PR #2).

- [x] `Plan the incremental v0.2 build and daily commit schedule`: this file, `EXECUTION_PLAN.md`, and approval status in PRD/SRS/README.
- [x] `Add FastAPI skeleton with configuration and SQLite migrations`: `app.py`, app factory, `.env`-aware settings, SQLite connection pragmas, `BEGIN IMMEDIATE` unit of work, migration runner, fixed categories, health check, base template, architecture test.
- [x] `Add exact money, allowance-cycle, and recurrence rules`: integer-cent parsing and formatting, cycle dates, injectable clock, recurrence expansion with property tests, README run instructions, and AI log rows.
- [x] Merge PR `Build the Float foundation` (PR #3).
- [x] `Reserve 4 October for testing, fixes, and polish` (branch `docs/testing-day-schedule`): this schedule change.
- [x] Merge PR `Reserve 4 October for testing and polish` (PR #4), ticked in the first commit of 1 October.

Evidence: AI log rows for the planning discussion, the foundation build, and this schedule change.

## Day 1 — Thursday 1 October: Identity and Ledger (P0)

Branch `feature/accounts-and-ledger`.

- [x] `Add accounts with scrypt passwords, sessions, and login throttling` (FR-01–03)
- [x] `Protect browser requests with sessions, CSRF tokens, and security headers` (FR-04, §9, NFR-10)
- [x] `Record ledger transactions with exact validation and an audit trail` (FR-06–08, FR-33 base)
- [x] `Add setup, transaction pages, and the recorded-balance dashboard` (FR-05, FR-28, FR-39)
- [x] `Emit the request log when Float runs`: unplanned. The day's final smoke test found that the NFR-10 log lines never reached the server output.
- [x] `Record the stack and domain-boundary decisions` (ADR-1, ADR-2, AI log)
- [x] Merge PR `Build accounts and the personal ledger` (PR #5).
- [x] `Rename branches to describe their content` (branch `docs/descriptive-branch-names`): unplanned, at the student's request.
- [x] Merge PR `Rename branches to describe their content` (PR #6).
- [x] `Fix the issues found by the Day 0–1 review` (branch `fix/review-findings`): unplanned, at the student's request, after a helper-agent review found 11 issues.
- [x] Merge PR `Fix the issues found by the Day 0–1 review` (PR #7). This box was ticked in the next day's first commit, so 1 October got no extra commit.

## Day 2 — Friday 2 October: Planning, safe-to-spend, and personal insight (P0 + P1)

Branch `feature/bills-goals-and-forecast`. The first four commits are P0; the next two are P1, in priority order.

- [x] `Materialize recurring bill occurrences idempotently` (FR-09–11)
- [x] `Pay, undo, skip, and split bill series atomically` (FR-12–13)
- [x] `Track savings goals with protect and release movements` (FR-14)
- [x] `Compute safe-to-spend with breakdown, reminder, and purchase preview` (FR-27–29)
- [x] `Forecast pace, runway, cash projection, and next-cycle outlook` (FR-30, personal data; household terms join on day 3)
- [x] `Plan goal contributions, budgets, and unusual-expense flags` (FR-15, FR-16, FR-31)
- [x] `Record the schema decision and log AI use` (ADR-3, AI log)
- [x] Merge PR `Build recurring bills, goals, safe-to-spend, and the forecast` (PR #8). This box was ticked in the next day's first commit, so 2 October kept exactly 8 commits.

## Day 3 — Saturday 3 October: Households, alerts, and the report draft (P0 + P1)

Branch `feature/households-and-alerts`. The first four commits are P0; the alerts and API commits are P1.

- [x] `Create households with single-use invitations and membership rules` (FR-17–19)
- [x] `Split shared expenses exactly with largest-remainder allocation` (FR-20–22)
- [x] `Show household balances, settle-up plans, and confirmed settlements` (FR-23–24)
- [x] `Reserve and pay household bills and complete the conservation tests` (FR-25–26, §4.5, household terms in the forecast)
- [x] `Add the alert centre and household activity feed` (FR-32–33)
- [ ] `Expose the JSON API with idempotency keys` (FR-34–35), only if time remains
- [ ] `Record the testing decision, final ADR, and report draft` (ADR-4, ADR-5, report draft, AI log)
- [ ] Merge PR `Build households, alerts, and the report draft`

## Day 4 — Sunday 4 October: testing, fixes, and polish (deadline 23:59)

Branch `release/testing-and-polish`. **No new features.** Merge by 20:00 to keep a buffer before the deadline.

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
- **1 October.** At the student's request, branches were renamed to describe their content instead of their date. The renames used GitHub's branch-rename API, and local branches follow:

  | Old name | New name |
  |---|---|
  | `docs/float-requirements` | `docs/allowance-planner-requirements` |
  | `docs/float-v2-requirements` | `docs/shared-living-requirements` |
  | `build/2026-09-30-foundation` | `feature/project-foundation` |
  | `docs/2026-09-30-replan-day4` | `docs/testing-day-schedule` |
  | `build/2026-10-01-identity-ledger` | `feature/accounts-and-ledger` |

  The branches for 2–4 October are now `feature/bills-goals-and-forecast`, `feature/households-and-alerts`, and `release/testing-and-polish`. Pull requests that were already merged still show their original branch names, because GitHub keeps the name a PR was merged from.
- **1 October.** At the student's request, a helper agent reviewed Days 0–1. Its 11 findings were fixed the same day in one extra commit on `fix/review-findings`, so 1 October has 11 commits. Migrations `0006` and `0007` hold the fixes, so the plan's later migrations start at `0008`.
