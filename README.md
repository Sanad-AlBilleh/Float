# Float

Float is a planned money co-pilot for students on an allowance who share a flat. It answers one question: **what can I safely spend today, after my bills, my share of the flat's costs, what I owe my flatmates, and my savings plan?**

It does this with:

- a recurrence engine for bills;
- households with shared expenses, fair cent-exact splits, simplified settle-up plans, and two-party settlement confirmation;
- goal contribution plans;
- a pace-based forecast of whether the money lasts until the next allowance.

## Project status

Requirements and design only. Version 0.2 of the requirements (30 September 2026) expands the original single-user allowance tracker after the professor's feedback that the idea and backend were too simple. No application has been implemented, no tests have been run, and professor approval of the revised scope has not yet been recorded. Obtain approval before writing application code, as Assignment 1 requires.

The proposed stack is Python/FastAPI with SQLite, server-rendered pages, and a JSON API, all in one process. It is organized as a modular monolith with three domains (Ledger, Planning, Households) plus Identity and Insights modules. Transactions are entered manually, EUR is the only currency, and the default allowance is €750 per month.

## Planned documentation

- `PRD.md`: user problem, v0.1 → v0.2 changes, product principles, scope and priorities (P0/P1/P2), and success criteria.
- `SRS.md`: functional requirements, exact calculation rules with worked fixtures, state machines, architecture, schema, security, and acceptance tests.
- `AI_USAGE.md`: meaningful AI interactions and the boundary between AI drafts and the student's own explanations.
- `ADR.md`: to be written as architecture decisions are finalized. Exactly five entries spanning at least three actual commit dates.

Setup instructions and a measured coverage result will be added after implementation. The final submission also needs a 4–5-page report and the written comprehension check.

## Assignment timeline

Deadline: **4 October 2026, 23:59**, in the course's deadline timezone.

The assignment requires at least 12 meaningful commits across at least six calendar days, pushed to GitHub on those days. No single day may contain more than 40% of the final commit total. Never fabricate or backdate commits.

Commits exist for 28 and 30 September. Nothing was pushed on 29 September, so reaching six days needs meaningful pushed work on every remaining date: 1, 2, 3, and 4 October. There is no buffer day left. Add truthful AI log entries and decisions as the work happens, not retrospectively.
