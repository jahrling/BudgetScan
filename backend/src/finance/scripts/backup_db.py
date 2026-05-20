"""Daily SQLite snapshot → gzip → Dropbox upload → verify → prune.

Invoked from scripts/backup_db.sh.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from finance.config import settings
from finance.services import dropbox_sync

logger = logging.getLogger(__name__)


def _sqlite_path() -> Path:
    # database_url is sqlite+aiosqlite:///<path>
    url = settings.database_url
    if "://" not in url:
        raise RuntimeError(f"Unrecognized DATABASE_URL: {url}")
    _, path = url.split("://", 1)
    # aiosqlite uses three-slash prefix; strip up to first non-slash
    return Path(path.lstrip("/"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    src = _sqlite_path()
    if not src.exists():
        print(json.dumps({"error": f"SQLite file not found: {src}"}))
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    remote_name = f"finance-{ts}.db.gz"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / f"finance-{ts}.db"
        shutil.copy2(src, snapshot)  # SQLite file copy is safe for personal-scale
        gz_path = snapshot.with_suffix(".db.gz")
        with open(snapshot, "rb") as fh_in, gzip.open(gz_path, "wb") as fh_out:
            shutil.copyfileobj(fh_in, fh_out)

        try:
            result = dropbox_sync.upload_backup(gz_path, remote_name)
            ok = dropbox_sync.verify_upload(result.dropbox_path, result.content_hash)
            if not ok:
                print(json.dumps({"error": "upload verification failed", "path": result.dropbox_path}))
                return 1
        except dropbox_sync.DropboxNotConfigured:
            print(json.dumps({"error": "DROPBOX_ACCESS_TOKEN not set"}))
            return 1
        except dropbox_sync.DropboxUploadError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1

    pruned = dropbox_sync.prune_old_backups(keep=30)
    print(
        json.dumps(
            {
                "uploaded": result.dropbox_path,
                "size_bytes": os.path.getsize(src),
                "pruned_count": len(pruned),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
