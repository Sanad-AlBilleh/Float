#!/usr/bin/env bash
# Partial-failure evidence for the A2 report (§8b): run with the compose stack up, from the repository root.
# bash scripts/capture_partial_failure.sh > docs/a2/evidence/partial-failure.md
set -u
P=http://localhost:8001/api/v1; H=http://localhost:8002/api/v1
TODAY=$(date +%F); FIRST=$(date +%Y-%m-01)
reg() { curl -s -X POST $P/auth/register -H 'content-type: application/json' -d "{\"username\":\"$1$RANDOM\",\"display_name\":\"$2\",\"password\":\"evidence passphrase 1\"}"; }
A=$(reg ana Ana); B=$(reg ben Ben)
TA=$(echo "$A" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'); IA=$(echo "$A" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["id"])')
TB=$(echo "$B" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'); IB=$(echo "$B" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["id"])')
for T in $TA $TB; do curl -s -o /dev/null -X POST $P/setup -H "authorization: Bearer $T" -H 'content-type: application/json' -d "{\"tracking_start\":\"$FIRST\",\"opening_balance_cents\":50000,\"allowance_day\":1,\"allowance_included\":true}"; done
HID=$(curl -s -X POST $H/households -H "authorization: Bearer $TA" -H 'content-type: application/json' -d '{"name":"Evidence flat"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
CODE=$(curl -s -X POST $H/households/$HID/invitations -H "authorization: Bearer $TA" | python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])')
curl -s -o /dev/null -X POST $H/households/join -H "authorization: Bearer $TB" -H 'content-type: application/json' -d "{\"code\":\"$CODE\"}"
EXP="{\"amount_cents\":3000,\"spent_on\":\"$TODAY\",\"category_id\":1,\"description\":\"Groceries\",\"split_method\":\"equal\",\"participants\":[{\"user_id\":$IA},{\"user_id\":$IB}]}"
curl -s -o /dev/null -X POST $H/households/$HID/expenses -H "authorization: Bearer $TA" -H 'content-type: application/json' -d "$EXP"
echo "# Partial-failure evidence, captured $(date -u +%FT%TZ) on the local compose stack"
echo; echo "## 1. Both services up: Ben's dashboard (household fields only)"
curl -s $P/dashboard -H "authorization: Bearer $TB" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps({k:d[k] for k in ("households_available",)}|{"household_payables_cents":d["terms"].get("household_payables_cents")}))'
echo; echo "## 2. households stopped: Ben's dashboard"
docker compose stop households >/dev/null 2>&1
curl -s -w '\nHTTP %{http_code} in %{time_total}s\n' $P/dashboard -H "authorization: Bearer $TB" | python3 -c '
import sys,json
raw=sys.stdin.read(); body,_,tail=raw.rpartition("\n"); body,_,status=body.rpartition("\n")
d=json.loads(body); print(json.dumps({k:v for k,v in d.items() if "household" in k or k in ("alerts_unchanged","notice")}, indent=1)); print(status)'
docker compose start households >/dev/null 2>&1; for i in $(seq 1 30); do curl -sf localhost:8002/health >/dev/null && break; sleep 2; done
echo; echo "## 3. personal stopped: household page, then recording a shared expense"
curl -s -o /dev/null $H/households/$HID -H "authorization: Bearer $TA"  # a read while personal is up saves the names (migration 002)
docker compose stop personal >/dev/null 2>&1
curl -s -w '\nHTTP %{http_code}\n' $H/households/$HID -H "authorization: Bearer $TA" | python3 -c '
import sys,json
raw=sys.stdin.read().rstrip("\n"); body,_,status=raw.rpartition("\n"); d=json.loads(body)
print(json.dumps({"members":[m["display_name"] for m in d["members"]]})); print(status)'
curl -s -w '\nHTTP %{http_code} in %{time_total}s\n' -X POST $H/households/$HID/expenses -H "authorization: Bearer $TA" -H 'content-type: application/json' -d "${EXP/3000/500}"
docker compose start personal >/dev/null 2>&1; for i in $(seq 1 30); do curl -sf localhost:8001/health >/dev/null && break; sleep 2; done
echo; echo "## 4. Both back: the household's expenses (nothing half-saved)"
curl -s $H/households/$HID/expenses -H "authorization: Bearer $TA" | python3 -c 'import sys,json;print([e["amount_cents"] for e in json.load(sys.stdin)])'
