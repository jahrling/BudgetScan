"""PDF credit card statements → import candidates via the local LLM.

Reuses the investment-statement OCR plumbing (``ocr.py``): PyMuPDF text per
page → Ollama text model, falling back to the vision model for pages without
a text layer. Each page is parsed separately so prompts stay small and one
bad page doesn't sink the statement.

LLM extraction can drop or misread a row, so we cross-check against the
statement's own summary: previous balance + charges − credits should equal
the new balance. A mismatch is surfaced to the user before anything is
written.

Jobs live in memory. Parsing a statement takes longer than the nginx proxy
timeout, so the router starts a job and the UI polls. The PDF itself is never
written to disk; a backend restart just means re-uploading.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from finance.models.account import Account
from finance.services import ocr
from finance.services.quicken import TransactionCandidate
from finance.services.statement_import import StatementParseResult

logger = logging.getLogger(__name__)

_SCHEMA = """{
  "summary": {
    "closing_date": "YYYY-MM-DD or null",
    "previous_balance": <number or null>,
    "new_balance": <number or null>
  } or null,
  "transactions": [
    {"trans_date": "MM/DD or null", "post_date": "MM/DD or null", "description": "string", "amount": <positive number>, "kind": "charge" | "credit"}
  ]
}"""

_EXAMPLE = """{
  "summary": {"closing_date": "2026-01-24", "previous_balance": 1250.40, "new_balance": 980.15},
  "transactions": [
    {"trans_date": "12/27", "post_date": "12/28", "description": "ACME COFFEE SEATTLE WA", "amount": 4.50, "kind": "charge"},
    {"trans_date": "01/05", "post_date": "01/05", "description": "ONLINE PAYMENT THANK YOU", "amount": 500.00, "kind": "credit"},
    {"trans_date": null, "post_date": "01/24", "description": "INTEREST CHARGE ON PURCHASES", "amount": 18.22, "kind": "charge"}
  ]
}"""

_RULES = """Rules:
- JSON only. No commentary, no markdown fences.
- Amounts are positive numbers in dollars. Use "kind" for direction:
  "charge" = purchases, fees, interest, cash advances (money owed goes up);
  "credit" = payments, refunds, returns, statement credits (money owed goes down).
- Each line of the page text is one row of the printed page. Take a
  transaction's date and amount from its own line only.
- Copy dates exactly as printed (usually MM/DD). If the statement has a
  transaction date and a posting date column, fill both; if it has only one
  date column, put it in "post_date" and set "trans_date" to null.
- Include every individual transaction line, including fees and interest
  charged.
- Do NOT include summary or total lines ("Total fees", "Purchases",
  "Payments and Credits", "New Balance", "Minimum Payment Due", etc.).
- "summary" is only for the account summary box (previous/new balance and
  closing date). Use null if this page has none. Do not invent values.
- If this page has no transactions, return "transactions": []."""

TEXT_PROMPT = f"""You are a credit card statement parser.

Parse the following page of a credit card statement into a single JSON object:

{_SCHEMA}

Example output:

{_EXAMPLE}

{_RULES}
"""

VISION_PROMPT = f"""You are a credit card statement parser.

Look at this page of a credit card statement and extract it as a single JSON
object:

{_SCHEMA}

Example output:

{_EXAMPLE}

{_RULES}
"""

# A page worth sending to the model has a date and a money amount somewhere.
# Not necessarily on one line: PyMuPDF often emits table columns as separate
# lines, so the date and amount of one row end up far apart in the text.
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}\b")
_MONEY_RE = re.compile(r"\d\.\d{2}\b")
# Below this, a page has no usable text layer (scanned) and goes to vision.
_MIN_TEXT_LAYER = 10

_JOB_TTL_SECONDS = 60 * 60


@dataclass
class Reconciliation:
    previous_balance_cents: int | None
    new_balance_cents: int | None
    charges_cents: int  # positive total of charges
    credits_cents: int  # positive total of credits
    # (previous + charges − credits) − new; None when the summary is missing.
    difference_cents: int | None


@dataclass
class PdfJob:
    id: str
    account: Account
    status: str = "running"  # 'running' | 'done' | 'failed'
    pages_total: int = 0
    pages_done: int = 0
    error: str | None = None
    result: StatementParseResult | None = None
    reconciliation: Reconciliation | None = None
    matched: bool = False
    created: float = field(default_factory=time.monotonic)


_jobs: dict[str, PdfJob] = {}
_tasks: set[asyncio.Task] = set()  # keep references so tasks aren't GC'd


def _prune() -> None:
    now = time.monotonic()
    for job_id in [j.id for j in _jobs.values() if now - j.created > _JOB_TTL_SECONDS]:
        _jobs.pop(job_id, None)


def get_job(job_id: str) -> PdfJob | None:
    return _jobs.get(job_id)


def start_job(raw: bytes, account: Account) -> PdfJob:
    _prune()
    job = PdfJob(id=uuid.uuid4().hex, account=account)
    _jobs[job.id] = job
    task = asyncio.create_task(_run(job, raw))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


_ROW_TOLERANCE_PT = 3.0


def _page_rows(page: Any) -> str:
    """Page text with each printed row on one line.

    Plain ``get_text()`` often emits table columns as separate runs, leaving
    the model to re-pair dates with amounts — which it gets wrong. Grouping
    words by vertical position and ordering by x rebuilds the visual rows.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    rows: list[tuple[float, list[tuple[float, float, str]]]] = []
    for x0, y0, x1, y1, word, *_ in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        mid = (y0 + y1) / 2
        if rows and abs(rows[-1][0] - mid) <= _ROW_TOLERANCE_PT:
            rows[-1][1].append((x0, x1, word))
        else:
            rows.append((mid, [(x0, x1, word)]))
    lines = []
    for _, cells in rows:
        cells.sort()
        parts = [cells[0][2]]
        for (_, prev_x1, _), (x0, _, word) in zip(cells, cells[1:]):
            # A wide gap is a column break; keep it visible to the model.
            parts.append(("   " if x0 - prev_x1 > 12 else " ") + word)
        lines.append("".join(parts))
    return "\n".join(lines)


def _page_texts(raw: bytes) -> list[str]:
    import pymupdf

    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        return [_page_rows(page) for page in doc]
    finally:
        doc.close()


async def _parse_page(
    images: "_PageImages", index: int, text: str
) -> dict[str, Any] | None:
    """Return the model's JSON for one page, or None if the page has nothing.

    Raises OCRError if the model can't produce JSON. Calls Ollama directly
    rather than via ``ocr.ocr_image_bytes``, which logs reply text — replies
    here are statement contents.
    """
    if len(text.strip()) >= _MIN_TEXT_LAYER:
        if not (_DATE_RE.search(text) and _MONEY_RE.search(text)):
            return None
        prompt = TEXT_PROMPT + "\n\nHere is the page text:\n\n" + text

        async def call() -> str:
            return await ocr.call_ollama_text(prompt, think=False)
    else:
        # No text layer (scanned) — render and use the vision model.
        jpeg = ocr.preprocess_image(await images.get(index))

        async def call() -> str:
            return await ocr.call_ollama_vision(jpeg, prompt=VISION_PROMPT)

    for attempt in range(2):
        try:
            return ocr.extract_json(await call())
        except ocr.OCRError:
            if attempt == 1:
                raise
    return None  # unreachable


class _PageImages:
    """Render the PDF to images once, and only if some page needs vision."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self._pages: list[bytes] | None = None

    async def get(self, index: int) -> bytes:
        if self._pages is None:
            # CPU-bound; keep it off the event loop.
            self._pages = await asyncio.to_thread(ocr.pdf_to_page_images, self._raw)
        return self._pages[index]


def _money_cents(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return round(float(str(v).replace("$", "").replace(",", "")) * 100)
    except ValueError:
        return None


def _parse_iso(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _resolve_date(raw: str, closing: date) -> datetime:
    """MM/DD → full date: the most recent such date on or before closing."""
    s = raw.strip()
    full = _parse_iso(s)
    if full is None:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                full = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                pass
    if full is None:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", s)
        if not m:
            raise ValueError(f"unparseable date {raw!r}")
        month, day = int(m.group(1)), int(m.group(2))
        year = closing.year if (month, day) <= (closing.month, closing.day) else closing.year - 1
        full = date(year, month, day)
    return datetime(full.year, full.month, full.day, tzinfo=timezone.utc)


def build_result(
    pages: list[dict[str, Any]],
    account: Account,
    today: date | None = None,
) -> tuple[StatementParseResult, Reconciliation]:
    """Turn per-page model output into candidates + a balance check."""
    result = StatementParseResult(format="pdf")
    # Model output is untrusted in shape as well as content.
    pages = [p for p in pages if isinstance(p, dict)]
    summary: dict[str, Any] = {}
    for page in pages:
        page_summary = page.get("summary")
        if not isinstance(page_summary, dict):
            continue
        for k, v in page_summary.items():
            if v is not None and summary.get(k) is None:
                summary[k] = v

    closing = _parse_iso(summary.get("closing_date"))
    if closing is None:
        closing = today or date.today()
        result.errors.append(
            "Couldn't read the statement closing date; years were assumed from "
            "today's date. Check dates if this is an older statement."
        )
    charges = credits = 0
    for page in pages:
        rows = page.get("transactions")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                result.errors.append("Skipped a row the model returned: not an object")
                continue
            try:
                amount = _money_cents(row.get("amount"))
                if amount is None:
                    raise ValueError("missing amount")
                amount = abs(amount)
                if amount == 0:
                    continue  # e.g. "Interest charge 0.00" — not a transaction
                kind = str(row.get("kind", "")).lower()
                if kind not in ("charge", "credit"):
                    raise ValueError(f"unknown kind {kind!r}")
                # Posted date, like the CSV/QFX imports, so dedup lines up.
                raw_date = row.get("post_date") or row.get("trans_date") or row.get("date")
                posted_at = _resolve_date(str(raw_date or ""), closing)
            except (ValueError, TypeError) as exc:
                result.errors.append(f"Skipped a row the model returned: {exc}")
                continue
            if kind == "charge":
                charges += amount
            else:
                credits += amount
            result.candidates.append(
                TransactionCandidate(
                    source_account_key=account.name,
                    account_id=account.id,
                    posted_at=posted_at,
                    amount_cents=-amount if kind == "charge" else amount,
                    description=(str(row.get("description") or "").strip() or None),
                    quicken_id=None,
                    currency=account.currency,
                )
            )

    result.candidates.sort(key=lambda c: c.posted_at)
    prev = _money_cents(summary.get("previous_balance"))
    new = _money_cents(summary.get("new_balance"))
    diff = None if prev is None or new is None else prev + charges - credits - new
    return result, Reconciliation(prev, new, charges, credits, diff)


async def _run(job: PdfJob, raw: bytes) -> None:
    try:
        texts = await asyncio.to_thread(_page_texts, raw)
        if not texts:
            raise ocr.OCRError("PDF has no pages")
        job.pages_total = len(texts)
        images = _PageImages(raw)
        pages: list[dict[str, Any]] = []
        page_errors: list[str] = []
        for i, text in enumerate(texts):
            try:
                parsed = await _parse_page(images, i, text)
            except ocr.OCRError as exc:
                # One unreadable page shouldn't sink the statement; the
                # balance check will show what's missing. No reply text in
                # the message — it would be statement contents.
                logger.warning("statement PDF page %d unreadable: %s", i + 1, type(exc).__name__)
                page_errors.append(f"Page {i + 1} couldn't be read by the model.")
                parsed = None
            if parsed is not None:
                pages.append(parsed)
            job.pages_done = i + 1
        job.result, job.reconciliation = build_result(pages, job.account)
        job.result.errors[:0] = page_errors
        if not job.result.candidates:
            job.result.errors.append(
                "No transactions found. If this is a scanned statement, the "
                "vision model may not have been able to read it."
            )
        job.status = "done"
    except Exception as exc:
        # Counts only — page text and model replies stay out of the logs.
        logger.warning(
            "statement PDF job failed: %s (pages %d/%d)",
            type(exc).__name__, job.pages_done, job.pages_total,
        )
        job.error = str(exc)[:500]
        job.status = "failed"
