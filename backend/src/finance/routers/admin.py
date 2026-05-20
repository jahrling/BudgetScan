"""Operator-facing read-only stats. Auth-gated to the single app user."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.config import settings
from finance.db import get_session
from finance.models.receipt import Receipt
from finance.services import dropbox_sync

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(current_user)],
)


def _db_size_bytes() -> int | None:
    url = settings.database_url
    if "://" not in url:
        return None
    _, path = url.split("://", 1)
    p = Path(path.lstrip("/"))
    try:
        return os.path.getsize(p)
    except OSError:
        return None


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    total = (await session.execute(select(func.count(Receipt.id)))).scalar_one()
    done = (
        await session.execute(
            select(func.count(Receipt.id)).where(Receipt.ocr_status == "done")
        )
    ).scalar_one()
    failed = (
        await session.execute(
            select(func.count(Receipt.id)).where(Receipt.ocr_status == "failed")
        )
    ).scalar_one()
    pending_sync = (
        await session.execute(
            select(func.count(Receipt.id)).where(
                Receipt.ocr_status == "done",
                Receipt.dropbox_path.is_(None),
            )
        )
    ).scalar_one()

    last_backup: str | None = None
    try:
        backups = dropbox_sync.list_backups()
        if backups:
            backups.sort(key=lambda t: t[1], reverse=True)
            last_backup = backups[0][1].astimezone(timezone.utc).isoformat()
    except dropbox_sync.DropboxNotConfigured:
        pass

    return {
        "receipts": {
            "total": total,
            "ocr_done": done,
            "ocr_failed": failed,
            "ocr_success_rate": (done / total) if total else None,
            "pending_dropbox_sync": pending_sync,
        },
        "db_size_bytes": _db_size_bytes(),
        "last_backup_at": last_backup,
        "app_env": settings.app_env,
        "now": datetime.now(timezone.utc).isoformat(),
    }
