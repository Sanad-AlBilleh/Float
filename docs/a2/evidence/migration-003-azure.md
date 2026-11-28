# Migration 003 on Azure (Assignment 2 §4.6)

Database `sgealbilleh-ieu2024-households-db` on `sgealbilleh-ieu2024-sql` (swedencentral), 28 November 2026. Queried with `sqlcmd` as the server admin, from my IP, with a firewall rule opened only for this and deleted afterwards.

1. First deploy (CD run https://github.com/Sanad-AlBilleh/Float/actions/runs/46156463620, commit `26692fa`) applied `001` and `002` to the empty databases.
2. In the live system I registered three users, created a household, had two join, and recorded three shared expenses (each also wrote the payer's ledger row in personal).
3. Before: the state below.
4. Merged PR #24; CD run https://github.com/Sanad-AlBilleh/Float/actions/runs/46159868937 (commit `fe3da16`) deployed it, and the container applied `003` at startup.
5. After: the state below. Every row is kept; the new column is filled for every real name; there were no stored `Member #id` fallbacks to clear on Azure.

## Before (after the first deploy and the data, before merging 003)

```
version|applied_at
-------|----------
001_init|2026-11-28 15:21:54.8784634
002_member_name|2026-11-28 15:21:54.8977949
id|household_id|user_id|member_name
--|------------|-------|-----------
1|1|1|Ana
2|1|2|Ben
3|1|3|Carla
memberships
-----------
3
shared_expenses
---------------
3
```

## Startup log line of the households container (`az containerapp logs show`)

```
migration applied: 003_member_name_saved_at.sql
```

## After

```
version|applied_at
-------|----------
001_init|2026-11-28 15:21:54.8784634
002_member_name|2026-11-28 15:21:54.8977949
003_member_name_saved_at|2026-11-28 15:28:49.0265698
id|household_id|user_id|member_name|member_name_saved_at
--|------------|-------|-----------|--------------------
1|1|1|Ana|2026-11-28 15:28:49
2|1|2|Ben|2026-11-28 15:28:49
3|1|3|Carla|2026-11-28 15:28:49
memberships
-----------
3
shared_expenses
---------------
3
```
