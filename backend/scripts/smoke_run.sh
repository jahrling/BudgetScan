#!/usr/bin/env bash
# End-to-end smoke against the stubbed-OCR server on :8765.
set -euo pipefail

BASE=http://127.0.0.1:8765/api
JAR=$(mktemp)
trap 'rm -f "$JAR" smoke_receipt.png' EXIT

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
get() { curl -s -b "$JAR" -c "$JAR" "$@"; }

say "health"
get "$BASE/health" | tee /dev/stderr | grep -q '"status":"ok"'

say "setup user"
get -X POST "$BASE/auth/setup" -H 'Content-Type: application/json' \
  -d '{"username":"smoke","password":"smoke"}' > /dev/null

say "create account"
ACCT_ID=$(get -X POST "$BASE/accounts" -H 'Content-Type: application/json' \
  -d '{"name":"Checking","type":"checking"}' | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "account=$ACCT_ID"

say "create Groceries category"
CAT_ID=$(get -X POST "$BASE/categories" -H 'Content-Type: application/json' \
  -d '{"name":"Groceries"}' | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "groceries=$CAT_ID"

say "generate test image"
python -c "from PIL import Image; Image.new('RGB',(128,128),(220,220,220)).save('smoke_receipt.png')"
ls -la smoke_receipt.png

say "upload receipt"
UP=$(get -X POST "$BASE/receipts" -F "file=@smoke_receipt.png;type=image/png")
echo "$UP"
RID=$(echo "$UP" | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "receipt_id=$RID"

say "force-process and poll"
get -X POST "$BASE/receipts/$RID/process?force=true" > /dev/null
for i in $(seq 1 20); do
  STATUS=$(get "$BASE/receipts/$RID" | python -c 'import sys,json;print(json.load(sys.stdin)["ocr_status"])')
  echo "  poll $i: $STATUS"
  [[ "$STATUS" == "done" ]] && break
  sleep 0.3
done
[[ "$STATUS" == "done" ]] || { echo "FAIL: OCR never completed"; exit 1; }

say "fetch parsed receipt"
get "$BASE/receipts/$RID" | python -m json.tool

say "fetch receipt image"
get "$BASE/receipts/$RID/image" -o /tmp/back.png
file /tmp/back.png || stat /tmp/back.png

say "materialize transaction"
TXN=$(get -X POST "$BASE/receipts/$RID/to-transaction" \
  -H 'Content-Type: application/json' \
  -d "{\"account_id\":$ACCT_ID}")
echo "$TXN" | python -m json.tool
TXN_ID=$(echo "$TXN" | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
AMT=$(echo "$TXN" | python -c 'import sys,json;print(json.load(sys.stdin)["amount_cents"])')
NLINES=$(echo "$TXN" | python -c 'import sys,json;print(len(json.load(sys.stdin)["line_items"]))')
SUM=$(echo "$TXN" | python -c 'import sys,json;d=json.load(sys.stdin);print(sum(li["amount_cents"] for li in d["line_items"]))')
echo "txn=$TXN_ID amount_cents=$AMT lines=$NLINES sum=$SUM"
[[ "$AMT" == "5000" ]] || { echo "FAIL: expected 5000"; exit 1; }
[[ "$SUM" == "5000" ]] || { echo "FAIL: line sum mismatch"; exit 1; }
[[ "$NLINES" == "4" ]] || { echo "FAIL: expected 4 lines (3 items + tax)"; exit 1; }

say "re-upload same image — should dedupe"
UP2=$(get -X POST "$BASE/receipts" -F "file=@smoke_receipt.png;type=image/png")
RID2=$(echo "$UP2" | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "second upload returned id=$RID2 (was $RID)"
[[ "$RID2" == "$RID" ]] || { echo "FAIL: dedupe broken"; exit 1; }

say "oversize upload — should 413"
python -c "open('big.bin','wb').write(b'x'*(11*1024*1024))"
HTTP=$(get -o /dev/null -w '%{http_code}' -X POST "$BASE/receipts" -F "file=@big.bin;type=application/octet-stream")
rm -f big.bin
echo "oversize http=$HTTP"
# Note: server may reject with 413 OR with 400 (FastAPI validation on type).
[[ "$HTTP" == "413" || "$HTTP" == "400" ]] || { echo "FAIL: expected 4xx on oversize, got $HTTP"; exit 1; }

printf '\n\033[1;32mALL SMOKE CHECKS PASSED\033[0m\n'
