"""Boot the FastAPI app with OCR + categorizer stubbed for smoke testing.

Run: python backend/scripts/smoke_serve.py
Then curl against http://127.0.0.1:8765.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Use a scratch DB + receipts dir so we don't touch prod data.
scratch = Path(tempfile.mkdtemp(prefix="bs_smoke_"))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{scratch / 'finance.db'}")
os.environ.setdefault("RECEIPTS_DIR", str(scratch / "receipts"))
os.environ.setdefault("APP_SECRET", "smoke-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finance.services import categorizer, ocr  # noqa: E402

FIXTURE = {
    "merchant": "Costco Wholesale",
    "date": "2026-05-15",
    "total": 50.00,
    "subtotal": 47.00,
    "tax": 3.00,
    "items": [
        {"description": "Milk 1 gal", "qty": 1, "unit_price": 4.99, "amount": 4.99},
        {"description": "Paper towels", "qty": 1, "unit_price": 19.99, "amount": 19.99},
        {"description": "Chicken thighs", "qty": 1, "unit_price": 22.02, "amount": 22.02},
    ],
}


async def fake_ocr(path, model=None):
    return FIXTURE


async def fake_llm(prompt: str) -> str:
    # Best-effort categorizer mock: route everything to whichever category
    # name shows up in the prompt that isn't "Uncategorized".
    lines = [
        line for line in prompt.splitlines() if line.strip().startswith(("1:", "2:", "3:", "4:", "5:"))
    ]
    target_id = None
    for line in lines:
        cid_str, _, name = line.partition(":")
        if "uncategorized" not in name.lower():
            target_id = int(cid_str.strip())
            break
    if target_id is None and lines:
        target_id = int(lines[0].split(":")[0].strip())
    if target_id is None:
        return "{}"
    mapping = {
        "milk 1 gal": target_id,
        "paper towels": target_id,
        "chicken thighs": target_id,
    }
    return json.dumps(mapping)


ocr.ocr_receipt_file = fake_ocr  # type: ignore[assignment]
categorizer._call_ollama_text = fake_llm  # type: ignore[assignment]

if __name__ == "__main__":
    import uvicorn

    print(f"Smoke server scratch dir: {scratch}")
    uvicorn.run("finance.main:app", host="127.0.0.1", port=8765, log_level="warning")
