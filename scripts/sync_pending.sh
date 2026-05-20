#!/usr/bin/env bash
# Hourly cron: retry Dropbox uploads for done-OCR receipts with no dropbox_path,
# then log what purge_old_receipts (dry-run) would delete.
#
# Install:
#   0 * * * *  cd /opt/finance && ./scripts/sync_pending.sh >> /var/log/finance-sync.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

exec docker compose exec -T backend python -m finance.scripts.sync_pending
