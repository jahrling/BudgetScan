"""Dropbox archive integration.

Receipt images live locally only as a staging buffer. Once OCR has written
its structured JSON to SQLite, the image is uploaded to Dropbox, verified
against the local sha256, and only then deleted from disk. The JSON in
SQLite is the operational record; the Dropbox image is the audit trail.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from finance.config import settings

logger = logging.getLogger(__name__)


# Dropbox computes content_hash as the hex-digest of concatenated sha256
# digests of each 4 MiB block of the file. See
# https://www.dropbox.com/developers/reference/content-hash
_DROPBOX_BLOCK = 4 * 1024 * 1024


def dropbox_content_hash(path: Path) -> str:
    block_hashes = b""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_DROPBOX_BLOCK)
            if not chunk:
                break
            block_hashes += hashlib.sha256(chunk).digest()
    return hashlib.sha256(block_hashes).hexdigest()


def dropbox_content_hash_bytes(data: bytes) -> str:
    block_hashes = b""
    for i in range(0, len(data), _DROPBOX_BLOCK):
        block_hashes += hashlib.sha256(data[i : i + _DROPBOX_BLOCK]).digest()
    return hashlib.sha256(block_hashes).hexdigest()


class DropboxNotConfigured(RuntimeError):
    """Raised when DROPBOX_ACCESS_TOKEN is empty."""


class DropboxUploadError(RuntimeError):
    pass


class DropboxVerificationError(RuntimeError):
    pass


@dataclass
class UploadResult:
    dropbox_path: str
    file_id: str
    content_hash: str


def _client():
    """Return a configured `dropbox.Dropbox` client.

    Lazy-imported so the dropbox SDK is not required for non-prod test runs.
    """
    if not settings.dropbox_access_token:
        raise DropboxNotConfigured(
            "DROPBOX_ACCESS_TOKEN is not set; Dropbox sync is disabled"
        )
    try:
        import dropbox  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — covered by smoke test
        raise DropboxNotConfigured(
            "dropbox-sdk-python is not installed. Add `dropbox` to pyproject.toml."
        ) from exc
    return dropbox.Dropbox(settings.dropbox_access_token)


def receipt_dropbox_path(
    sha256: str, captured_at: datetime | None = None, ext: str = ".webp"
) -> str:
    when = captured_at or datetime.now(timezone.utc)
    root = settings.dropbox_root_folder.rstrip("/")
    return f"{root}/{when.year:04d}/{when.month:02d}/{sha256}{ext}"


def upload_receipt(local_path: Path, sha256: str, captured_at: datetime | None = None) -> UploadResult:
    """Upload a local receipt image to Dropbox.

    Returns the Dropbox path and file ID on success.
    Raises DropboxUploadError on any API failure.
    """
    client = _client()
    import dropbox  # type: ignore[import-not-found]

    ext = local_path.suffix.lower() or ".jpg"
    dropbox_path = receipt_dropbox_path(sha256, captured_at, ext=ext)
    try:
        with open(local_path, "rb") as fh:
            data = fh.read()
        meta = client.files_upload(
            data,
            dropbox_path,
            mode=dropbox.files.WriteMode.overwrite,
            mute=True,
        )
    except Exception as exc:  # noqa: BLE001 — surface as upload error
        raise DropboxUploadError(f"Dropbox upload failed for {dropbox_path}: {exc}") from exc

    return UploadResult(
        dropbox_path=meta.path_display or dropbox_path,
        file_id=meta.id,
        content_hash=getattr(meta, "content_hash", "") or "",
    )


def verify_upload(dropbox_path: str, expected_content_hash: str) -> bool:
    """Confirm the file exists on Dropbox and its content_hash matches."""
    client = _client()
    try:
        meta = client.files_get_metadata(dropbox_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Dropbox metadata lookup failed for %s: %s", dropbox_path, exc)
        return False
    remote_hash = getattr(meta, "content_hash", None)
    if not remote_hash:
        return False
    if remote_hash != expected_content_hash:
        logger.error(
            "Dropbox content_hash mismatch for %s (remote=%s expected=%s)",
            dropbox_path,
            remote_hash,
            expected_content_hash,
        )
        return False
    return True


def delete_after_confirmed(local_path: Path, dropbox_path: str, expected_content_hash: str) -> None:
    """Unlink the local file only after Dropbox confirms the hash matches.

    Raises DropboxVerificationError if verification fails. The local file is
    left in place so the retry cron can pick it up.
    """
    if not verify_upload(dropbox_path, expected_content_hash):
        raise DropboxVerificationError(
            f"Dropbox verification failed for {dropbox_path}; local file kept for retry"
        )
    try:
        os.unlink(local_path)
    except FileNotFoundError:
        pass


_MONTH_RE = re.compile(r"/(\d{4})/(\d{2})(?:/|$)")


def _parse_captured_from_path(path: str) -> datetime | None:
    m = _MONTH_RE.search(path)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
    except ValueError:
        return None


def _months_between(older: datetime, newer: datetime) -> int:
    return (newer.year - older.year) * 12 + (newer.month - older.month)


def purge_old_receipts(months: int = 36, confirm: bool = False) -> dict[str, list[str]]:
    """List receipts older than `months` and optionally delete them.

    Returns a dict {"deleted": [...], "would_delete": [...]} so callers can log.
    Dry-run by default; pass confirm=True from a manual operator run only.
    """
    client = _client()
    root = settings.dropbox_root_folder
    deleted: list[str] = []
    would_delete: list[str] = []
    now = datetime.now(timezone.utc)

    try:
        result = client.files_list_folder(root, recursive=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("purge_old_receipts: could not list %s: %s", root, exc)
        return {"deleted": deleted, "would_delete": would_delete}

    entries: list = list(result.entries)
    while getattr(result, "has_more", False):
        result = client.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)

    for entry in entries:
        path = getattr(entry, "path_lower", None) or getattr(entry, "path_display", None)
        if not path or path.endswith("/"):
            continue
        captured = _parse_captured_from_path(path)
        if captured is None:
            continue
        if _months_between(captured, now) < months:
            continue
        if confirm:
            try:
                client.files_delete_v2(path)
                deleted.append(path)
            except Exception as exc:  # noqa: BLE001
                logger.error("purge: failed to delete %s: %s", path, exc)
        else:
            would_delete.append(path)

    return {"deleted": deleted, "would_delete": would_delete}


def upload_backup(local_path: Path, remote_name: str) -> UploadResult:
    """Upload a DB backup snapshot to /finance-backups/db/<remote_name>."""
    client = _client()
    import dropbox  # type: ignore[import-not-found]

    folder = settings.dropbox_backup_folder.rstrip("/")
    dropbox_path = f"{folder}/{remote_name}"
    with open(local_path, "rb") as fh:
        data = fh.read()
    try:
        meta = client.files_upload(
            data, dropbox_path, mode=dropbox.files.WriteMode.overwrite, mute=True
        )
    except Exception as exc:  # noqa: BLE001
        raise DropboxUploadError(f"Backup upload failed: {exc}") from exc
    return UploadResult(
        dropbox_path=meta.path_display or dropbox_path,
        file_id=meta.id,
        content_hash=getattr(meta, "content_hash", "") or "",
    )


def list_backups() -> list[tuple[str, datetime]]:
    """Return [(path, server_modified)] for files under the backup folder."""
    client = _client()
    folder = settings.dropbox_backup_folder
    try:
        result = client.files_list_folder(folder)
    except Exception as exc:  # noqa: BLE001
        logger.error("list_backups: %s", exc)
        return []
    out: list[tuple[str, datetime]] = []
    for entry in result.entries:
        path = getattr(entry, "path_lower", None) or getattr(entry, "path_display", None)
        modified = getattr(entry, "server_modified", None)
        if path and modified:
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            out.append((path, modified))
    return out


def prune_old_backups(keep: int = 30) -> list[str]:
    """Delete all but the most-recent `keep` backups. Returns deleted paths."""
    client = _client()
    backups = sorted(list_backups(), key=lambda t: t[1], reverse=True)
    to_delete = backups[keep:]
    deleted: list[str] = []
    for path, _ in to_delete:
        try:
            client.files_delete_v2(path)
            deleted.append(path)
        except Exception as exc:  # noqa: BLE001
            logger.error("prune_old_backups: failed to delete %s: %s", path, exc)
    return deleted
