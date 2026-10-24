#!/usr/bin/env bash
# End-to-end check of a deployed FraudShield API, including the database.
# Usage:  bash deploy/smoke-test.sh https://<your-app>.azurecontainerapps.io
#
# Uses a fresh random UPI ID each run, so it never mixes with real report data.
set -euo pipefail

URL=${1:?usage: bash deploy/smoke-test.sh https://your-app-url}
URL=${URL%/}
SCAMMER="smoke.$RANDOM$RANDOM@ybl"
pass=0; fail=0
ok()  { echo "  PASS  $1"; pass=$((pass+1)); }
bad() { echo "  FAIL  $1"; fail=$((fail+1)); }
field() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "Testing $URL with test identifier $SCAMMER"

echo "1. Health"
curl -sf "$URL/v1/health" | grep -q '"status":"ok"' && ok "API is up" || bad "health"

echo "2. Monday: a new scammer, nobody has reported it yet"
MON="Your KYC is pending. Account will be blocked today. Pay Rs 10 to verify at $SCAMMER"
r=$(curl -sf -X POST "$URL/v1/check" -H 'Content-Type: application/json' -d "{\"message\":\"$MON\"}")
echo "        verdict=$(echo "$r" | field "['verdict']")  text=$(echo "$r" | field "['text_probability']")  reporters=$(echo "$r" | field "['reporters']")"
[ "$(echo "$r" | field "['reporters']")" = "0" ] && ok "no reports yet" || bad "expected 0 reporters"

echo "3. Five different people report it (writes to Postgres)"
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/v1/reports" -H 'Content-Type: application/json' \
    -d "{\"message\":\"$MON\",\"reporter_id\":\"smoke-device-$RANDOM-$i\",\"category\":\"kyc_freeze\"}")
  [ "$code" = "201" ] || bad "report $i returned $code"
done
ok "5 reports accepted"

echo "4. The same person reporting again counts once"
dup=$(curl -sf -X POST "$URL/v1/reports" -H 'Content-Type: application/json' \
  -d "{\"message\":\"$MON\",\"reporter_id\":\"repeat-device-001\",\"category\":\"kyc_freeze\"}" >/dev/null &&
      curl -sf -X POST "$URL/v1/reports" -H 'Content-Type: application/json' \
  -d "{\"message\":\"$MON\",\"reporter_id\":\"repeat-device-001\",\"category\":\"kyc_freeze\"}")
[ "$(echo "$dup" | field "['duplicates'][0]['value']")" = "$SCAMMER" ] && ok "duplicate ignored" || bad "duplicate not detected"

echo "5. Friday: different wording, same UPI ID"
FRI="Dear customer, complete re-verification by paying Rs 1 to $SCAMMER"
r=$(curl -sf -X POST "$URL/v1/check" -H 'Content-Type: application/json' -d "{\"message\":\"$FRI\"}")
v=$(echo "$r" | field "['verdict']"); n=$(echo "$r" | field "['reporters']")
echo "        verdict=$v  probability=$(echo "$r" | field "['probability']")  text=$(echo "$r" | field "['text_probability']")  reporters=$n"
echo "        reasons: $(echo "$r" | field "['reasons']")"
[ "$n" = "6" ] && ok "6 distinct reporters counted" || bad "expected 6 reporters, got $n"
case "$v" in likely_scam|confirmed_scam) ok "verdict raised by reports" ;; *) bad "verdict was $v" ;; esac

echo "6. Lookup works with any formatting"
curl -sf "$URL/v1/entities?q=$(echo "$SCAMMER" | tr a-z A-Z)" | grep -q "\"reporters_recent\":6" && ok "history lookup" || bad "lookup"

echo "7. Normal message stays safe"
r=$(curl -sf -X POST "$URL/v1/check" -H 'Content-Type: application/json' \
  -d '{"message":"482910 is your OTP for txn of Rs 2,499 at AMAZON. Do not share with anyone. -HDFC Bank"}')
[ "$(echo "$r" | field "['verdict']")" = "safe" ] && ok "OTP is safe" || bad "OTP flagged: $(echo "$r" | field "['verdict']")"

echo
echo "$pass passed, $fail failed"
[ "$fail" = "0" ]
