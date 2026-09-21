"""Statement image storage, OCR orchestration, and snapshot materialization."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance.config import settings
from finance.models.position_snapshot import PositionSnapshot
from finance.models.security import Security
from finance.models.statement_scan import StatementScan
from finance.services import ocr as ocr_service

logger = logging.getLogger(__name__)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"}

MICROS = 1_000_000

_STATEMENT_SCHEMA = """{
  "account_name": "string or null",
  "statement_date": "YYYY-MM-DD or null",
  "holdings": [
    {
      "symbol": "string or null",
      "name": "string",
      "quantity": <number>,
      "price": <number, per-share in dollars, or null>,
      "market_value": <number, total in dollars>,
      "cost_basis": <number, total in dollars, or null>
    }
  ]
}"""

_STATEMENT_EXAMPLE = """{
  "account_name": "Brokerage Account",
  "statement_date": "2025-06-30",
  "holdings": [
    {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "quantity": 150.0, "price": 285.42, "market_value": 42813.00, "cost_basis": 38500.00},
    {"symbol": "VXUS", "name": "Vanguard Total Intl Stock ETF", "quantity": 200.0, "price": 62.15, "market_value": 12430.00, "cost_basis": 11800.00},
    {"symbol": null, "name": "Fidelity Growth Fund", "quantity": 45.123, "price": 88.50, "market_value": 3993.39, "cost_basis": null}
  ]
}"""

_STATEMENT_RULES = """Rules:
- JSON only. No commentary, no markdown fences.
- Dollar amounts are in dollars (e.g. 12345.67, not cents).
- Quantity is number of shares/units (can be fractional).
- If a field is missing or unclear, use null. Do not invent values.
- Include every distinct holding row in the statement.
- Exclude rows labeled "Total", "Subtotal", "Account Summary", or any
  aggregate/summary line.
- Include cash, money market, and sweep account balances as holdings
  (quantity=1, price=market_value for cash positions).
- For mutual funds without a ticker, use the fund name and leave symbol null."""

STATEMENT_PROMPT = f"""You are an investment statement parser.

Look at this brokerage/retirement account statement image and extract the
holdings table as a single JSON object:

{_STATEMENT_SCHEMA}

Example output for a statement with three holdings:

{_STATEMENT_EXAMPLE}

{_STATEMENT_RULES}
"""

STATEMENT_TEXT_PROMPT = f"""You are an investment statement parser.

Parse the following brokerage/retirement account statement text and extract the
holdings table as a single JSON object:

{_STATEMENT_SCHEMA}

Example output for a statement with three holdings:

{_STATEMENT_EXAMPLE}

{_STATEMENT_RULES}
"""


def _ext_for(filename: str, content_type: str | None, raw: bytes | None = None) -> str:
    if raw and ocr_service.is_pdf(raw):
        return ".pdf"
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXTS:
        return ".jpg" if suffix == ".jpeg" else suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed and guessed.lower() in ALLOWED_EXTS:
            return guessed.lower()
    return ".jpg"


def _storage_path(sha256: str, ext: str, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    base = Path(settings.statements_dir)
    return base / f"{now.year:04d}" / f"{now.month:02d}" / f"{sha256}{ext}"


def _dollars_to_cents(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def _dollars_to_micros(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(round(float(v) * MICROS))
    except (TypeError, ValueError):
        return None


def _quantity_to_micros(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(round(float(v) * MICROS))
    except (TypeError, ValueError):
        return None


async def store_upload(
    session: AsyncSession,
    *,
    raw: bytes,
    original_filename: str,
    content_type: str | None,
) -> tuple[StatementScan, bool]:
    if len(raw) > settings.max_receipt_upload_bytes:
        raise HTTPException(status_code=413, detail="Statement file exceeds 10 MB limit")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    if ocr_service.is_pdf(raw):
        try:
            import pymupdf
            doc = pymupdf.open(stream=raw, filetype="pdf")
            if doc.page_count == 0:
                raise HTTPException(status_code=400, detail="PDF has no pages")
            doc.close()
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=400, detail=f"Upload is not a valid PDF: {exc}"
            ) from exc
    else:
        try:
            from PIL import Image, UnidentifiedImageError

            with Image.open(io.BytesIO(raw)) as probe:
                probe.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Upload is not a valid image: {exc}"
            ) from exc

    digest = hashlib.sha256(raw).hexdigest()

    existing = await session.execute(
        select(StatementScan).where(StatementScan.sha256 == digest)
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found, False

    ext = _ext_for(original_filename, content_type, raw)
    path = _storage_path(digest, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)

    scan = StatementScan(
        file_path=str(path),
        original_filename=original_filename,
        sha256=digest,
        ocr_status="pending",
    )
    session.add(scan)
    await session.commit()
    await session.refresh(scan)
    return scan, True


async def get_scan(session: AsyncSession, scan_id: int) -> StatementScan:
    scan = await session.get(StatementScan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Statement scan not found")
    return scan


async def run_ocr(session: AsyncSession, scan_id: int) -> StatementScan:
    scan = await get_scan(session, scan_id)
    path = Path(scan.file_path)
    try:
        if not path.exists():
            raise ocr_service.OCRError(f"Statement file missing on disk: {path}")
        raw = path.read_bytes()
        if ocr_service.is_pdf(raw):
            parsed, method = await ocr_service.ocr_pdf_bytes(
                raw, prompt=STATEMENT_PROMPT, text_prompt=STATEMENT_TEXT_PROMPT,
            )
        else:
            parsed = await ocr_service.ocr_image_bytes(raw, prompt=STATEMENT_PROMPT)
            method = "vision"
        scan.ocr_raw_json = json.dumps(parsed)
        scan.ocr_model = settings.ollama_text_model if method == "text" else settings.ollama_vision_model
        scan.ocr_status = "done"
        scan.ocr_error = None
    except Exception as exc:
        logger.exception("OCR failed for statement scan %s", scan_id)
        scan.ocr_status = "failed"
        scan.ocr_error = str(exc)[:500]
    await session.commit()
    await session.refresh(scan)
    return scan


async def process_in_background(
    session_factory: async_sessionmaker[AsyncSession],
    scan_id: int,
) -> None:
    async with session_factory() as session:
        await run_ocr(session, scan_id)


async def _match_security(
    session: AsyncSession, symbol: str | None, name: str
) -> tuple[int | None, str | None]:
    """Try to match a holding to an existing Security. Returns (id, name) or (None, None)."""
    if symbol:
        result = await session.execute(
            select(Security).where(
                func.upper(Security.symbol) == symbol.upper()
            )
        )
        sec = result.scalar_one_or_none()
        if sec:
            return sec.id, sec.name

    if name:
        result = await session.execute(
            select(Security).where(
                func.upper(Security.name) == name.upper()
            )
        )
        sec = result.scalar_one_or_none()
        if sec:
            return sec.id, sec.name

    return None, None


async def build_review_preview(
    session: AsyncSession, scan_id: int
) -> dict[str, Any]:
    scan = await get_scan(session, scan_id)
    if scan.ocr_status != "done" or not scan.ocr_raw_json:
        raise HTTPException(
            status_code=400,
            detail=f"Statement not ready for review (status={scan.ocr_status})",
        )

    try:
        parsed = json.loads(scan.ocr_raw_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Statement JSON is corrupt: {exc}"
        ) from exc

    holdings = parsed.get("holdings") or []
    positions = []
    for h in holdings:
        name = h.get("name") or ""
        symbol = h.get("symbol")
        qty_micros = _quantity_to_micros(h.get("quantity"))
        if qty_micros is None:
            continue
        price_micros = _dollars_to_micros(h.get("price"))
        mv_cents = _dollars_to_cents(h.get("market_value"))
        if mv_cents is None:
            continue
        cb_cents = _dollars_to_cents(h.get("cost_basis"))

        matched_id, matched_name = await _match_security(session, symbol, name)

        positions.append({
            "symbol": symbol,
            "name": name,
            "quantity_micros": qty_micros,
            "price_micros": price_micros,
            "market_value_cents": mv_cents,
            "cost_basis_cents": cb_cents,
            "matched_security_id": matched_id,
            "matched_security_name": matched_name,
        })

    return {
        "account_name": parsed.get("account_name"),
        "statement_date": parsed.get("statement_date"),
        "positions": positions,
    }


async def _get_or_create_security(
    session: AsyncSession,
    *,
    security_id: int | None,
    symbol: str | None,
    name: str,
) -> int:
    """Resolve or create a Security row. Returns the security id."""
    if security_id:
        sec = await session.get(Security, security_id)
        if sec:
            return sec.id

    if symbol:
        result = await session.execute(
            select(Security).where(
                func.upper(Security.symbol) == symbol.upper()
            )
        )
        sec = result.scalar_one_or_none()
        if sec:
            return sec.id

    if name:
        result = await session.execute(
            select(Security).where(
                func.upper(Security.name) == name.upper()
            )
        )
        sec = result.scalar_one_or_none()
        if sec:
            return sec.id

    sec = Security(name=name, symbol=symbol, security_type="other")
    session.add(sec)
    await session.flush()
    return sec.id


async def materialize_snapshots(
    session: AsyncSession,
    scan_id: int,
    *,
    account_id: int,
    as_of: date,
    positions: list[dict[str, Any]],
) -> list[PositionSnapshot]:
    scan = await get_scan(session, scan_id)

    await session.execute(
        PositionSnapshot.__table__.delete().where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.as_of == as_of,
            PositionSnapshot.source == "ocr",
        )
    )

    resolved: dict[int, dict[str, Any]] = {}
    for pos in positions:
        sec_id = await _get_or_create_security(
            session,
            security_id=pos.get("security_id"),
            symbol=pos.get("symbol"),
            name=pos["name"],
        )
        if sec_id in resolved:
            existing = resolved[sec_id]
            existing["quantity_micros"] += pos["quantity_micros"]
            existing["market_value_cents"] += pos["market_value_cents"]
            if existing.get("price_micros") is None:
                existing["price_micros"] = pos.get("price_micros")
            cb = existing.get("cost_basis_cents")
            pcb = pos.get("cost_basis_cents")
            if cb is not None and pcb is not None:
                existing["cost_basis_cents"] = cb + pcb
            elif pcb is not None:
                existing["cost_basis_cents"] = pcb
        else:
            resolved[sec_id] = {
                "quantity_micros": pos["quantity_micros"],
                "market_value_cents": pos["market_value_cents"],
                "price_micros": pos.get("price_micros"),
                "cost_basis_cents": pos.get("cost_basis_cents"),
            }

    snapshots: list[PositionSnapshot] = []
    for sec_id, data in resolved.items():
        snap = PositionSnapshot(
            account_id=account_id,
            security_id=sec_id,
            as_of=as_of,
            quantity_micros=data["quantity_micros"],
            market_value_cents=data["market_value_cents"],
            price_micros=data.get("price_micros"),
            cost_basis_cents=data.get("cost_basis_cents"),
            source="ocr",
        )
        session.add(snap)
        snapshots.append(snap)

    scan.account_id = account_id
    scan.as_of = as_of

    await session.flush()
    await session.commit()
    for snap in snapshots:
        await session.refresh(snap)
    return snapshots
