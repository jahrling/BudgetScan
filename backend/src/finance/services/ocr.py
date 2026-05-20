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


async def call_ollama_vision(jpeg_bytes: bytes, *, model: str | None = None) -> str:
    """Call Ollama with the receipt image. Returns the raw model response text."""
    model_name = model or settings.ollama_vision_model
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": PROMPT,
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


async def ocr_receipt_bytes(raw: bytes, *, model: str | None = None) -> dict[str, Any]:
    """Run the full OCR pipeline on raw image bytes.

    Retries the JSON extraction once if the first reply is unparseable.
    """
    jpeg = preprocess_image(raw)
    last_text = ""
    for attempt in range(2):
        text = await call_ollama_vision(jpeg, model=model)
        last_text = text
        try:
            return extract_json(text)
        except OCRError:
            if attempt == 1:
                logger.warning("OCR JSON parse failed twice; last reply=%r", text[:500])
                raise OCRError(f"Could not parse JSON after retry. Last reply: {text[:200]}")
            continue
    # Unreachable, but keeps mypy happy.
    raise OCRError(f"Unexpected OCR loop exit. Last reply: {last_text[:200]}")


async def ocr_receipt_file(path: Path, *, model: str | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    return await ocr_receipt_bytes(raw, model=model)
