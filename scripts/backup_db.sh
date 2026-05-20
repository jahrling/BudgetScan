#!/usr/bin/env bash
# Daily 02:00 cron: snapshot SQLite → gzip → upload to Dropbox → verify → prune.
#
# Install:
#   0 2 * * *  cd /opt/finance && ./scripts/backup_db.sh >> /var/log/finance-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

exec docker compose exec -T backend python -m finance.scripts.backup_db
