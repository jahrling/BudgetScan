#!/usr/bin/env bash
# End-to-end smoke test against a running BudgetScan instance.
# Exits 0 on pass, 1 on any failure.
#
# Usage:
#   BASE_URL=https://finance.local ./scripts/smoke_test.sh
#   (defaults to http://localhost:8000)
#
# Requires: curl, jq
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
USER="smoke-$$"
PASS="smoke-pass-$(date +%s)"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR" /tmp/smoke-receipt-*.png' EXIT

say()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
fail() { printf "\n\033[1;31m✗ %s\033[0m\n" "$*"; exit 1; }
pass() { printf "\033[1;32m✓\033[0m %s\n" "$*"; }

req() {
  curl -fsSL -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"
}

say "Checking /api/health"
req "$BASE_URL/api/health" | jq -e '.status == "ok"' >/dev/null || fail "health check failed"
pass "health ok"

say "Bootstrapping user (setup or login)"
if req -o /dev/null -w "%{http_code}" \
   -H "Content-Type: application/json" \
   -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
   "$BASE_URL/api/auth/setup" | grep -qE '^(201|409)$'; then
  # If 409, try login with these creds (won't match; fall through to an existing dev user).
  req -X POST -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
    "$BASE_URL/api/auth/login" >/dev/null 2>&1 || \
    fail "could not authenticate — supply existing creds via USER/PASS env vars and rerun"
fi
pass "authenticated"

say "Creating a category"
CAT_ID=$(req -X POST -H "Content-Type: application/json" \
  -d '{"name":"SmokeTest"}' \
  "$BASE_URL/api/categories" | jq -r '.id')
pass "category $CAT_ID"

say "Creating an account"
ACC_ID=$(req -X POST -H "Content-Type: application/json" \
  -d '{"name":"Smoke Checking","type":"checking"}' \
  "$BASE_URL/api/accounts" | jq -r '.id')
pass "account $ACC_ID"

say "Creating a budget"
req -X POST -H "Content-Type: application/json" \
  -d "{\"category_id\":$CAT_ID,\"period\":\"monthly\",\"amount_cents\":50000,\"start_date\":\"2026-05-01\"}" \
  "$BASE_URL/api/budgets" >/dev/null
pass "budget created"

say "Uploading a fixture receipt"
python3 - <<'PY' >/dev/null
from PIL import Image
Image.new("RGB",(64,64),color=(220,220,220)).save("/tmp/smoke-receipt-1.png","PNG")
PY
R_JSON=$(curl -fsSL -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -F "file=@/tmp/smoke-receipt-1.png;type=image/png" \
  "$BASE_URL/api/receipts")
R_ID=$(echo "$R_JSON" | jq -r '.id')
[ -n "$R_ID" ] && [ "$R_ID" != "null" ] || fail "upload returned no id: $R_JSON"
pass "receipt $R_ID"

say "Polling OCR (up to 90s)"
for i in $(seq 1 45); do
  STATUS=$(req "$BASE_URL/api/receipts/$R_ID" | jq -r '.ocr_status')
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 2
done
[ "$STATUS" = "done" ] || fail "OCR did not complete (status=$STATUS)"
pass "OCR done"

say "Verifying Dropbox archive"
DROPBOX_PATH=$(req "$BASE_URL/api/receipts/$R_ID" | jq -r '.dropbox_path // empty')
if [ -z "$DROPBOX_PATH" ]; then
  echo "  (warning) dropbox_path not set — Dropbox sync may be disabled"
else
  pass "archived at $DROPBOX_PATH"
fi

say "Checking /api/admin/stats"
req "$BASE_URL/api/admin/stats" | jq -e '.receipts.total >= 1' >/dev/null || fail "admin stats failed"
pass "admin stats reachable"

say "QIF export (optional)"
if req -o /tmp/smoke.qif -w "%{http_code}" \
   "$BASE_URL/api/transactions/export.qif" | grep -q '^200$'; then
  pass "QIF export ok"
else
  echo "  (warning) /api/transactions/export.qif not present — skipping"
fi

say "Logging out"
req -X POST "$BASE_URL/api/auth/logout" >/dev/null || true
pass "logged out"

printf "\n\033[1;32mSMOKE TEST PASSED\033[0m\n"
