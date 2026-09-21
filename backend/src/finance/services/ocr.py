"""Vision-LLM receipt OCR via Ollama.

The model is asked to return strict JSON with merchant/date/total/items.
We preprocess images with Pillow (auto-orient + downscale + JPEG q=90) so the
payload to Ollama stays reasonable.

This service is intentionally tolerant: any failure surfaces as a structured
error string the router can persist on the Receipt row.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from finance.config import settings

logger = logging.getLogger(__name__)

MAX_LONG_EDGE = 2048
JPEG_QUALITY = 90

PROMPT = """You are a receipt-parsing assistant.

Look at the receipt image and extract its contents as a single JSON object
with exactly this shape:

{
  "merchant": "string",
  "date": "YYYY-MM-DD",
  "total": <number, dollars>,
  "subtotal": <number, dollars or null>,
  "tax": <number, dollars or null>,
  "items": [
    {
      "description": "string",
      "qty": <number or null>,
      "unit_price": <number or null>,
      "amount": <number>
    }
  ]
}

Rules:
- Respond with JSON only. No commentary, no markdown fences.
- Amounts are in dollars (e.g. 12.34, not 1234).
- If a field is illegible, use null. Do not invent values.
- "items" must sum (approximately) to "subtotal" if subtotal is present, or
  to "total" minus "tax" otherwise. If you cannot read line items, return
  an empty array rather than guessing.
"""


class OCRError(RuntimeError):
    """Raised when OCR cannot produce usable JSON for a receipt."""


def preprocess_image(raw: bytes) -> bytes:
    """Auto-orient, downscale long edge to 2048px, re-encode as JPEG q=90.

    Returns JPEG bytes. Strips alpha for non-RGB inputs (HEIC/PNG with
    transparency).
    """
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        long_edge = max(w, h)
        if long_edge > MAX_LONG_EDGE:
            scale = MAX_LONG_EDGE / long_edge
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from a model's reply.

    Strips code fences first; if that's still not valid, finds the largest
    {...} substring and tries that. Raises OCRError if nothing parses.
    """
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Fallback: greedy match the first { ... last }
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OCRError(f"Model returned non-JSON: {exc}") from exc
    raise OCRError("Model returned no JSON-looking content")


async def call_ollama_vision(
    jpeg_bytes: bytes,
    *,
    prompt: str | None = None,
    model: str | None = None,
) -> str:
    """Call Ollama vision with an image. Returns the raw model response text."""
    model_name = model or settings.ollama_vision_model
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt or PROMPT,
        "images": [b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return str(data.get("response", ""))


async def call_ollama_text(
    prompt: str,
    *,
    model: str | None = None,
) -> str:
    """Call Ollama with a text-only prompt. Returns the raw model response text."""
    model_name = model or settings.ollama_text_model
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload: dict[str, Any] = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    timeout = httpx.Timeout(settings.ollama_timeout_seconds, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    response = str(data.get("response", ""))
    logger.info(
        "call_ollama_text: model=%s, prompt_len=%d, response_len=%d, done=%s",
        model_name, len(prompt), len(response), data.get("done"),
    )
    return response


def pdf_to_page_images(raw: bytes, *, dpi: int = 200) -> list[bytes]:
    """Render each page of a PDF to JPEG bytes using PyMuPDF."""
    import pymupdf

    doc = pymupdf.open(stream=raw, filetype="pdf")
    pages: list[bytes] = []
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        pages.append(pix.tobytes("jpeg"))
    doc.close()
    return pages


def is_pdf(raw: bytes) -> bool:
    return raw[:5] == b"%PDF-"


async def ocr_image_bytes(
    raw: bytes,
    *,
    prompt: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Preprocess an image, call Ollama vision, and extract JSON.

    Retries the JSON extraction once if the first reply is unparseable.
    """
    jpeg = preprocess_image(raw)
    last_text = ""
    for attempt in range(2):
        text = await call_ollama_vision(jpeg, prompt=prompt, model=model)
        last_text = text
        try:
            return extract_json(text)
        except OCRError:
            if attempt == 1:
                logger.warning("OCR JSON parse failed twice; last reply=%r", text[:500])
                raise OCRError(f"Could not parse JSON after retry. Last reply: {text[:200]}")
            continue
    raise OCRError(f"Unexpected OCR loop exit. Last reply: {last_text[:200]}")


MIN_TEXT_CHARS = 200


def extract_pdf_text(raw: bytes) -> str:
    """Extract text from all pages of a PDF. Returns empty string if no text layer."""
    import pymupdf

    doc = pymupdf.open(stream=raw, filetype="pdf")
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n".join(parts)


async def parse_pdf_text(
    text: str,
    *,
    prompt: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Send extracted PDF text to the text LLM for structured extraction."""
    model_name = model or settings.ollama_text_model
    full_prompt = (prompt or "") + "\n\nHere is the statement text:\n\n" + text
    logger.info(
        "parse_pdf_text: sending %d chars of text to %s (prompt %d + text %d)",
        len(full_prompt), model_name, len(prompt or ""), len(text),
    )
    for attempt in range(2):
        try:
            reply = await call_ollama_text(full_prompt, model=model)
        except Exception as exc:
            raise OCRError(
                f"Ollama text call failed (model={model_name}): {exc}"
            ) from exc
        logger.info("parse_pdf_text attempt %d: got %d chars back", attempt + 1, len(reply))
        if not reply.strip():
            if attempt == 1:
                raise OCRError(
                    f"Model {model_name} returned empty response for PDF text "
                    f"({len(text)} chars extracted, {len(full_prompt)} char prompt). "
                    f"Check that the model is loaded: ollama list"
                )
            continue
        try:
            return extract_json(reply)
        except OCRError:
            if attempt == 1:
                raise OCRError(
                    f"Model {model_name} returned non-JSON after retry. "
                    f"Text extracted: {len(text)} chars. Last reply: {reply[:300]}"
                )
    raise OCRError(
        f"Model {model_name} returned empty response for PDF text "
        f"({len(text)} chars extracted). Check that the model is loaded: ollama list"
    )


async def ocr_pdf_bytes(
    raw: bytes,
    *,
    prompt: str | None = None,
    text_prompt: str | None = None,
    model: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Extract holdings from a PDF. Tries text extraction first; falls back to vision OCR.

    Returns (parsed_dict, method) where method is "text" or "vision".
    """
    pdf_text = extract_pdf_text(raw)
    text_len = len(pdf_text.strip())

    if text_len >= MIN_TEXT_CHARS:
        logger.info("PDF has %d chars of extractable text; using text model", text_len)
        try:
            result = await parse_pdf_text(pdf_text, prompt=text_prompt or prompt, model=model)
            return result, "text"
        except OCRError as text_err:
            logger.warning("Text extraction failed (%s); falling back to vision OCR", text_err)
            text_error = text_err
    else:
        text_error = None

    logger.info("PDF using vision OCR (text chars: %d, threshold: %d)", text_len, MIN_TEXT_CHARS)
    try:
        pages = pdf_to_page_images(raw)
        if not pages:
            raise OCRError("PDF has no pages")

        all_results: list[dict[str, Any]] = []
        for i, jpeg in enumerate(pages):
            parsed = None
            for attempt in range(2):
                text = await call_ollama_vision(jpeg, prompt=prompt, model=model)
                try:
                    parsed = extract_json(text)
                    break
                except OCRError:
                    if attempt == 1:
                        logger.warning("PDF page %d JSON parse failed twice; last reply=%r", i, text[:500])
            if parsed is not None:
                all_results.append(parsed)

        if not all_results:
            raise OCRError("No pages produced parseable JSON")

        return _merge_page_results(all_results), "vision"
    except Exception as vision_err:
        parts = ["PDF processing failed."]
        if text_error:
            parts.append(f"Text extraction ({text_len} chars): {text_error}")
        parts.append(f"Vision fallback: {vision_err}")
        raise OCRError(" | ".join(parts)) from vision_err


def _merge_page_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine OCR results from multiple PDF pages into one."""
    merged: dict[str, Any] = {}
    all_holdings: list[dict[str, Any]] = []
    for r in results:
        if not merged.get("account_name") and r.get("account_name"):
            merged["account_name"] = r["account_name"]
        if not merged.get("statement_date") and r.get("statement_date"):
            merged["statement_date"] = r["statement_date"]
        all_holdings.extend(r.get("holdings") or [])
    merged["holdings"] = all_holdings
    return merged


async def ocr_receipt_bytes(raw: bytes, *, model: str | None = None) -> dict[str, Any]:
    return await ocr_image_bytes(raw, model=model)


async def ocr_receipt_file(path: Path, *, model: str | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    return await ocr_receipt_bytes(raw, model=model)
