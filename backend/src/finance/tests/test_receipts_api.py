"""Receipt upload + OCR + to-transaction tests.

Ollama is mocked at the service layer so tests run without a real model.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from finance.db import get_session
from finance.main import app
from finance.models import Base
from finance.services import categorizer as categorizer_service
from finance.services import ocr as ocr_service
from finance.services import receipt as receipt_service


def _png_bytes(color: tuple[int, int, int] = (220, 220, 220)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "finance.services.receipt.settings.receipts_dir", str(tmp_path / "receipts")
    )
    # Default: OCR returns a canned fixture. Individual tests override.
    categorizer_service.clear_cache()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    # Background OCR opens its own session via async_session_factory.
    # Swap it for the test factory so it hits the in-memory DB.
    monkeypatch.setattr("finance.routers.receipts.async_session_factory", factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "test", "password": "test"})
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


FIXTURE_OCR_JSON: dict[str, Any] = {
    "merchant": "Costco Wholesale",
    "date": "2026-05-15",
    "total": 50.00,
    "subtotal": 47.00,
    "tax": 3.00,
    "items": [
        {"description": "Milk 1 gal", "qty": 1, "unit_price": 4.99, "amount": 4.99},
        {"description": "Paper towels 12pk", "qty": 1, "unit_price": 19.99, "amount": 19.99},
        {"description": "Chicken thighs 4lb", "qty": 1, "unit_price": 22.02, "amount": 22.02},
    ],
}


# ── upload + dedupe ──


async def test_upload_returns_pending_receipt(client: AsyncClient, monkeypatch) -> None:
    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return FIXTURE_OCR_JSON

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)

    image = _png_bytes()
    resp = await client.post(
        "/api/receipts",
        files={"file": ("receipt.png", image, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ocr_status"] in {"pending", "done"}
    assert body["sha256"]


async def test_upload_dedupes_by_sha256(client: AsyncClient, monkeypatch) -> None:
    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return FIXTURE_OCR_JSON

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)

    image = _png_bytes()
    r1 = await client.post("/api/receipts", files={"file": ("a.png", image, "image/png")})
    r2 = await client.post("/api/receipts", files={"file": ("b.png", image, "image/png")})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


async def test_upload_rejects_oversize(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "finance.services.receipt.settings.max_receipt_upload_bytes", 100
    )
    image = _png_bytes()
    resp = await client.post(
        "/api/receipts", files={"file": ("r.png", image, "image/png")}
    )
    assert resp.status_code == 413


# ── processing ──


async def test_process_endpoint_stores_parsed_json(
    client: AsyncClient, monkeypatch
) -> None:
    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return FIXTURE_OCR_JSON

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)

    image = _png_bytes()
    up = await client.post(
        "/api/receipts", files={"file": ("r.png", image, "image/png")}
    )
    receipt_id = up.json()["id"]

    # BackgroundTasks attached to upload may not have run yet under ASGITransport;
    # explicitly trigger processing to make the test deterministic.
    resp = await client.post(f"/api/receipts/{receipt_id}/process?force=true")
    assert resp.status_code == 200

    # Poll up to a few cycles for the background task to flip status.
    for _ in range(20):
        r = await client.get(f"/api/receipts/{receipt_id}")
        if r.json()["ocr_status"] == "done":
            break
    body = r.json()
    assert body["ocr_status"] == "done", body
    raw = json.loads(body["ocr_raw_json"])
    assert raw["merchant"] == "Costco Wholesale"
    assert len(raw["items"]) == 3


async def test_failed_ocr_records_error(client: AsyncClient, monkeypatch) -> None:
    async def boom(path: Path, model: str | None = None) -> dict[str, Any]:
        raise ocr_service.OCRError("model unreachable")

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", boom)

    image = _png_bytes()
    up = await client.post(
        "/api/receipts", files={"file": ("r.png", image, "image/png")}
    )
    rid = up.json()["id"]
    await client.post(f"/api/receipts/{rid}/process?force=true")
    for _ in range(20):
        r = await client.get(f"/api/receipts/{rid}")
        if r.json()["ocr_status"] == "failed":
            break
    assert r.json()["ocr_status"] == "failed"
    assert "model unreachable" in r.json()["ocr_error"]


# ── to-transaction ──


async def test_to_transaction_creates_splits(client: AsyncClient, monkeypatch) -> None:
    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return FIXTURE_OCR_JSON

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)

    # Categorizer LLM returns Groceries for everything to keep the test simple.
    cat_resp = await client.post("/api/categories", json={"name": "Groceries"})
    groceries_id = cat_resp.json()["id"]

    async def fake_llm_call(prompt: str) -> str:
        return json.dumps(
            {
                "milk 1 gal": groceries_id,
                "paper towels 12pk": groceries_id,
                "chicken thighs 4lb": groceries_id,
            }
        )

    monkeypatch.setattr(categorizer_service, "_call_ollama_text", fake_llm_call)

    acct = (
        await client.post("/api/accounts", json={"name": "Checking", "type": "checking"})
    ).json()

    up = await client.post(
        "/api/receipts", files={"file": ("r.png", _png_bytes(), "image/png")}
    )
    rid = up.json()["id"]
    await client.post(f"/api/receipts/{rid}/process?force=true")
    for _ in range(20):
        if (await client.get(f"/api/receipts/{rid}")).json()["ocr_status"] == "done":
            break

    resp = await client.post(
        f"/api/receipts/{rid}/to-transaction",
        json={"account_id": acct["id"]},
    )
    assert resp.status_code == 200, resp.text
    txn = resp.json()
    assert txn["amount_cents"] == 5000
    assert txn["receipt_id"] == rid
    # 3 item lines + 1 tax/rounding balancer = 4 lines
    assert len(txn["line_items"]) == 4
    line_total = sum(li["amount_cents"] for li in txn["line_items"])
    assert line_total == 5000


async def test_to_transaction_with_unparseable_items_falls_back(
    client: AsyncClient, monkeypatch
) -> None:
    """Items present but their sum is way off the total → single uncategorized line."""

    bad = {**FIXTURE_OCR_JSON, "items": [{"description": "??", "amount": 999}]}

    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return bad

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)

    acct = (
        await client.post("/api/accounts", json={"name": "Checking", "type": "checking"})
    ).json()
    up = await client.post(
        "/api/receipts", files={"file": ("r.png", _png_bytes(), "image/png")}
    )
    rid = up.json()["id"]
    await client.post(f"/api/receipts/{rid}/process?force=true")
    for _ in range(20):
        if (await client.get(f"/api/receipts/{rid}")).json()["ocr_status"] == "done":
            break

    resp = await client.post(
        f"/api/receipts/{rid}/to-transaction", json={"account_id": acct["id"]}
    )
    assert resp.status_code == 200
    txn = resp.json()
    assert len(txn["line_items"]) == 1
    assert txn["line_items"][0]["amount_cents"] == 5000
    assert txn["line_items"][0]["category_name"] == "Uncategorized"


# ── categorizer graceful fallback ──


async def test_categorizer_falls_back_when_ollama_unreachable(
    client: AsyncClient, monkeypatch
) -> None:
    """If the text LLM raises, every item must still get a category id."""

    async def fake_ocr(path: Path, model: str | None = None) -> dict[str, Any]:
        return FIXTURE_OCR_JSON

    async def boom(prompt: str) -> str:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ocr_service, "ocr_receipt_file", fake_ocr)
    monkeypatch.setattr(categorizer_service, "_call_ollama_text", boom)

    acct = (
        await client.post("/api/accounts", json={"name": "Checking", "type": "checking"})
    ).json()
    up = await client.post(
        "/api/receipts", files={"file": ("r.png", _png_bytes(), "image/png")}
    )
    rid = up.json()["id"]
    await client.post(f"/api/receipts/{rid}/process?force=true")
    for _ in range(20):
        if (await client.get(f"/api/receipts/{rid}")).json()["ocr_status"] == "done":
            break

    resp = await client.post(
        f"/api/receipts/{rid}/to-transaction", json={"account_id": acct["id"]}
    )
    assert resp.status_code == 200
    txn = resp.json()
    # Should not 500 — every line item resolves to Uncategorized.
    for li in txn["line_items"]:
        assert li["category_name"] == "Uncategorized"


# ── JSON extraction edge cases ──


def test_extract_json_strips_code_fences() -> None:
    text = '```json\n{"a": 1, "b": "x"}\n```'
    assert ocr_service.extract_json(text) == {"a": 1, "b": "x"}


def test_extract_json_finds_embedded_object() -> None:
    text = 'Sure! Here you go:\n{"merchant": "X", "total": 1}\nlet me know.'
    assert ocr_service.extract_json(text) == {"merchant": "X", "total": 1}


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(ocr_service.OCRError):
        ocr_service.extract_json("not json at all")


def test_preprocess_downscales_large_image() -> None:
    big = Image.new("RGB", (4000, 3000), color=(0, 0, 0))
    buf = io.BytesIO()
    big.save(buf, format="JPEG")
    out = ocr_service.preprocess_image(buf.getvalue())
    reloaded = Image.open(io.BytesIO(out))
    assert max(reloaded.size) == 2048
