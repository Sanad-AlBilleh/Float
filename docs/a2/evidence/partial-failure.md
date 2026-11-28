# Partial-failure evidence, captured 2026-11-28T14:43:50Z on the local compose stack

## 1. Both services up: Ben's dashboard (household fields only)
{"households_available": true, "household_payables_cents": 1500}

## 2. households stopped: Ben's dashboard
{
 "household_receivables_cents": 0,
 "household_receivables_display": "\u20ac0.00",
 "in_household": false,
 "households_available": false
}
HTTP 200 in 0.019627s

## 3. personal stopped: household page, then recording a shared expense
{"members": ["Ana", "Ben"]}
HTTP 200
{"type":"about:blank","title":"Ledger unavailable","status":503,"detail":"Your ledger is unavailable right now, so nothing was saved. Try again in a minute."}
HTTP 503 in 0.014373s

## 4. Both back: the household's expenses (nothing half-saved)
[3000]
