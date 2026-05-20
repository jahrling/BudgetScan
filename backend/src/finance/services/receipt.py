"""Receipt storage, OCR orchestration, and transaction materialization."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance.config import settings
from finance.models.line_item import LineItem
from finance.models.merchant import Merchant
from finance.models.receipt import Receipt
from finance.models.transaction import Transaction
from finance.services import dropbox_sync, ocr as ocr_service
from finance.services.categorizer import suggest_categories
from finance.services.merchant import maybe_update_default_category
from finance.services.transaction import (
    _get_or_create_uncategorized,
    get_transaction_with_items,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def _ext_for(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXTS:
        return ".jpg" if suffix == ".jpeg" else suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed and guessed.lower() in ALLOWED_EXTS:
            return guessed.lower()
    return ".jpg"


def storage_path_for(sha256: str, ext: str, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    base = Path(settings.receipts_dir)
    return base / f"{now.year:04d}" / f"{now.month:02d}" / f"{sha256}{ext}"


async def store_upload(
    session: AsyncSession,
    *,
    raw: bytes,
    original_filename: str,
    content_type: str | None,
) -> tuple[Receipt, bool]:
    """Persist a receipt upload, dedupe by sha256.

    Returns (receipt, created). When `created` is False the caller uploaded
    an image we already had — the existing row is returned untouched.
    """
    if len(raw) > settings.max_receipt_upload_bytes:
        raise HTTPException(status_code=413, detail="Receipt image exceeds 10 MB limit")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    # Validate the upload is actually a decodable image. verify() consumes
    # the stream, so we re-open afterwards if we ever needed the object —
    # here we only need the format check.
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Upload is not a valid image: {exc}"
        ) from exc

    digest = hashlib.sha256(raw).hexdigest()

    existing = await session.execute(select(Receipt).where(Receipt.sha256 == digest))
    found = existing.scalar_one_or_none()
    if found is not None:
        return found, False

    ext = _ext_for(original_filename, content_type)
    path = storage_path_for(digest, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)

    receipt = Receipt(
        file_path=str(path),
        original_filename=original_filename,
        sha256=digest,
        captured_at=datetime.now(timezone.utc),
        ocr_status="pending",
    )
    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)
    return receipt, True


async def get_receipt(session: AsyncSession, receipt_id: int) -> Receipt:
    receipt = await session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


async def run_ocr(session: AsyncSession, receipt_id: int) -> Receipt:
    """Synchronously process a receipt. Returns the updated row.

    Used both by the background task and by tests.
    """
    receipt = await get_receipt(session, receipt_id)
    path = Path(receipt.file_path)
    try:
        if not path.exists():
            raise ocr_service.OCRError(f"Receipt file missing on disk: {path}")
        parsed = await ocr_service.ocr_receipt_file(path)
        receipt.ocr_raw_json = json.dumps(parsed)
        receipt.ocr_model = settings.ollama_vision_model
        receipt.ocr_status = "done"
        receipt.ocr_error = None
    except Exception as exc:  # noqa: BLE001 — record failure, don't crash
        logger.exception("OCR failed for receipt %s", receipt_id)
        receipt.ocr_status = "failed"
        receipt.ocr_error = str(exc)[:500]
    await session.commit()
    await session.refresh(receipt)

    # If OCR succeeded, upload to Dropbox and delete the local image.
    # Any failure here leaves the local file in place for the retry cron;
    # OCR success is not rolled back.
    if receipt.ocr_status == "done" and not receipt.dropbox_path:
        await _archive_to_dropbox(session, receipt)
    return receipt


async def _archive_to_dropbox(session: AsyncSession, receipt: Receipt) -> None:
    path = Path(receipt.file_path)
    if not path.exists():
        return
    try:
        result = dropbox_sync.upload_receipt(
            path, receipt.sha256, captured_at=receipt.captured_at
        )
        dropbox_sync.delete_after_confirmed(
            path, result.dropbox_path, result.content_hash
        )
        receipt.dropbox_path = result.dropbox_path
        await session.commit()
        await session.refresh(receipt)
    except dropbox_sync.DropboxNotConfigured:
        logger.warning(
            "Dropbox not configured; receipt %s kept locally", receipt.id
        )
    except (
        dropbox_sync.DropboxUploadError,
        dropbox_sync.DropboxVerificationError,
    ) as exc:
        logger.error("Dropbox archive failed for receipt %s: %s", receipt.id, exc)


async def retry_pending_uploads(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    """Sweep done-OCR receipts that haven't been archived. Used by the cron."""
    attempted = 0
    succeeded = 0
    failed = 0
    async with session_factory() as session:
        rows = await session.execute(
            select(Receipt).where(
                Receipt.ocr_status == "done",
                Receipt.dropbox_path.is_(None),
            )
        )
        for receipt in rows.scalars().all():
            if not Path(receipt.file_path).exists():
                continue
            attempted += 1
            await _archive_to_dropbox(session, receipt)
            if receipt.dropbox_path:
                succeeded += 1
            else:
                failed += 1
    return {"attempted": attempted, "succeeded": succeeded, "failed": failed}


async def process_in_background(
    session_factory: async_sessionmaker[AsyncSession],
    receipt_id: int,
) -> None:
    """Background-task wrapper: opens its own session so the request can return."""
    async with session_factory() as session:
        await run_ocr(session, receipt_id)


def _to_cents(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


async def materialize_transaction(
    session: AsyncSession,
    receipt_id: int,
    *,
    account_id: int,
    merchant_id: int | None,
) -> dict:
    """Create a transaction + line_items from a completed receipt's parsed JSON.

    Categorizer is best-effort; failures default to merchant default / Uncategorized.
    """
    receipt = await get_receipt(session, receipt_id)
    if receipt.ocr_status != "done" or not receipt.ocr_raw_json:
        raise HTTPException(
            status_code=400,
            detail=f"Receipt not ready for transaction (status={receipt.ocr_status})",
        )

    try:
        parsed = json.loads(receipt.ocr_raw_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Receipt JSON is corrupt: {exc}"
        ) from exc

    posted_at = _parse_date(parsed.get("date")) or receipt.captured_at
    total_cents = _to_cents(parsed.get("total"))
    if total_cents is None or total_cents <= 0:
        raise HTTPException(
            status_code=400,
            detail="Parsed receipt has no usable total amount",
        )

    items_raw = parsed.get("items") or []
    items_cents: list[tuple[dict[str, Any], int]] = []
    for it in items_raw:
        amt = _to_cents(it.get("amount"))
        if amt is None or amt <= 0:
            continue
        items_cents.append((it, amt))

    merchant: Merchant | None = None
    if merchant_id is not None:
        merchant = await session.get(Merchant, merchant_id)

    # Build line items: if any are present, ask the categorizer; otherwise
    # create a single Uncategorized line for the whole total.
    txn = Transaction(
        account_id=account_id,
        merchant_id=merchant_id,
        posted_at=posted_at,
        amount_cents=total_cents,
        description=parsed.get("merchant"),
        receipt_id=receipt.id,
        status="pending",
    )
    session.add(txn)
    await session.flush()

    if items_cents:
        suggestions = await suggest_categories(
            session,
            [it for it, _ in items_cents],
            merchant=merchant,
        )
        items_sum = sum(c for _, c in items_cents)
        drift = total_cents - items_sum
        tax_cents = _to_cents(parsed.get("tax")) or 0

        # Big mismatch (>$1 and not matching tax) → fall back to a single
        # Uncategorized line so totals are guaranteed to balance. The user
        # can still split manually after.
        if abs(drift) > 100 and abs(drift - tax_cents) > 5:
            uncategorized = await _get_or_create_uncategorized(session)
            session.add(
                LineItem(
                    transaction_id=txn.id,
                    category_id=uncategorized.id,
                    description=parsed.get("merchant"),
                    amount_cents=total_cents,
                )
            )
        else:
            for (it, amt_cents), cat_id in zip(items_cents, suggestions, strict=True):
                session.add(
                    LineItem(
                        transaction_id=txn.id,
                        category_id=cat_id,
                        description=str(it.get("description") or ""),
                        quantity=_safe_float(it.get("qty")),
                        unit_price_cents=_to_cents(it.get("unit_price")),
                        amount_cents=amt_cents,
                        user_modified=False,
                    )
                )
            if drift != 0:
                uncategorized = await _get_or_create_uncategorized(session)
                session.add(
                    LineItem(
                        transaction_id=txn.id,
                        category_id=uncategorized.id,
                        description="Tax / rounding",
                        amount_cents=drift,
                    )
                )
            line_count = len(items_cents) + (1 if drift != 0 else 0)
            txn.status = "split" if line_count > 1 else "pending"
    else:
        uncategorized = await _get_or_create_uncategorized(session)
        session.add(
            LineItem(
                transaction_id=txn.id,
                category_id=uncategorized.id,
                description=parsed.get("merchant"),
                amount_cents=total_cents,
            )
        )

    await session.commit()
    await session.refresh(txn)

    if txn.merchant_id:
        await maybe_update_default_category(session, txn.merchant_id)

    return await get_transaction_with_items(session, txn.id)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
