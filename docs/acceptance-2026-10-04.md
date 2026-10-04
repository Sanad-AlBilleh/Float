# Acceptance pass, 4 October 2026

Measured on the development machine: Apple M5, macOS 26.6, Python 3.14.7. Every number below was produced by a command run on 4 October; nothing is estimated.

## Fresh clone (AT-29, NFR-01–04)

`git clone` of the `release/testing-and-polish` branch into an empty folder, then `python3 -m venv .venv`, `pip install -r requirements.txt`, and `python app.py` with `PORT` and `DATA_DIR` set:

- The server started without `.env`, without a manual migration step, and without any other service.
- `GET /healthz` answered 200, and the registration page rendered.
- The full suite passed in the clone (575 tests at that point), and the working tree stayed clean.

## Automated tests and coverage (NFR-08)

| Measure | Result |
|---|---|
| `pytest` | 598 passed |
| Coverage of the business modules (identity, ledger, planning, households, insights, application, shared) | 97% (2,910 statements, 83 missed) |
| Coverage of all modules | 95% (4,794 statements, 245 missed) |

## Performance (AT-31, NFR-05)

`python scripts/perf_smoke.py` builds the SRS synthetic dataset and prints the rows it created:
- 3 users in one household;
- 16,000 transactions (15,000 personal plus the 1,000 payer rows of shared expenses);
- 1,000 shared expenses;
- 20 bill series.

| Measure | Result | Limit |
|---|---|---|
| Ready (app built and answering) | 62 ms | 5,000 ms |
| Dashboard, 50 requests, materialization and alerts included | median 47 ms, p95 48 ms, max 68 ms | p95 500 ms |

## Review findings from 3 October

A helper agent (Claude Opus 5.5) reviewed the whole app on 3 October and found 9 problems. Each was fixed on 4 October with a failing test written first, one commit each (two related messages share a commit):

| # | Severity | Problem | Fix commit |
|---|---|---|---|
| 1 | High | Editing or deleting an old shared expense changed the balance of someone who had left | `Fix a former member's balance changing after they left` |
| 2 | Medium | "This and future" dropped a bill's end date | `Fix "this and future" dropping a bill's end date` |
| 3 | Medium | A 0% household bill participant caused a 500 | `Fix a server error for a 0% household bill participant` |
| 4 | Medium | An overdue household bill became unpayable after someone left | `Fix an overdue household bill becoming unpayable after someone leaves` |
| 5 | Medium | Extreme dates and numbers caused 500s; API 500s were HTML | `Fix server errors from extreme dates and numbers` |
| 6 | Low | Former members could see current balances and bills | `Hide current balances and bills from former members` |
| 7, 8 | Low | A settlement notice read the wrong way round; cancelling showed no message | `Fix two settlement messages` |
| 9 | Low | Documentation claimed the "fewest" transfers and missed two API differences | `Correct the settle-up wording and the API differences` |

## Browser checks (part of AT-30)

The redesigned pages were checked in a browser at desktop width (1280 px) and phone width (375 px):
- dashboard, transactions, the transaction form, bills, goals, budgets, categories, households, alerts, and setup;
- the bottom tab bar and the More sheet.

These problems were found and fixed the same day:
- progress bars ignored their widths, because the Content Security Policy forbids inline styles (they are now SVG);
- stale stylesheets were served from the browser cache (the stylesheet link is now versioned);
- several layout issues the student pointed out.

## Still to do by the student

- **The journey walkthrough (PRD §6), done by the student.** Use the demo account created with `scripts/seed_demo.py`, and time PRD goals G1 (under 2 minutes) and G2 (under 3 minutes).
- **The rest of the AT-30 manual checks:**
  - keyboard-only use;
  - a cross-site form post being refused in a real browser;
  - a stale-edit conflict.
