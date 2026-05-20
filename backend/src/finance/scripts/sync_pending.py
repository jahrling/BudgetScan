"""Retry-cron entrypoint. Reruns archive for done-OCR receipts that
have no dropbox_path yet, then logs (dry-run) what purge would delete.

Invoked from scripts/sync_pending.sh inside the backend container.
"""

from __future__ import annotations

import asyncio
import json
import logging

from finance.db import async_session_factory
from finance.services import dropbox_sync
from finance.services.receipt import retry_pending_uploads

logger = logging.getLogger(__name__)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        stats = await retry_pending_uploads(async_session_factory)
    except dropbox_sync.DropboxNotConfigured:
        print(json.dumps({"error": "DROPBOX_ACCESS_TOKEN not set"}))
        return 1

    purge = {"deleted": [], "would_delete": []}
    try:
        purge = dropbox_sync.purge_old_receipts(months=36, confirm=False)
    except dropbox_sync.DropboxNotConfigured:
        pass

    print(
        json.dumps(
            {
                "sync": stats,
                "purge_dry_run": {
                    "would_delete_count": len(purge["would_delete"]),
                    "sample": purge["would_delete"][:5],
                },
            }
        )
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
