"""PDF statement parsing: date/year resolution, signs, balance check, job API.

The LLM is stubbed; fixtures are synthetic (SECURITY.md §4).
"""

import asyncio
import json
from datetime import date

import pytest
from httpx import AsyncClient

from finance.models.account import Account
from finance.services import statement_pdf
from finance.tests.test_quicken import _account, client  # noqa: F401  (fixture)


def _acct() -> Account:
    a = Account(name="Test Card", type="credit", currency="USD")
    a.id = 1
    return a


PAGE_1 = {
    "summary": {"closing_date": "2026-01-24", "previous_balance": 1000.00, "new_balance": 522.13},
    "transactions": [
        {"trans_date": "12/27", "post_date": "12/28", "description": "ACME COFFEE", "amount": 4.50, "kind": "charge"},
        {"post_date": "01/05", "description": "ONLINE PAYMENT", "amount": 500.00, "kind": "credit"},
    ],
}
PAGE_2 = {
    "summary": None,
    "transactions": [
        {"trans_date": "01/10", "post_date": None, "description": "TEST GROCERY", "amount": "17.63", "kind": "charge"},
    ],
}


def test_year_rollover_signs_and_balanced():
    result, rec = statement_pdf.build_result([PAGE_1, PAGE_2], _acct())
    got = [(c.posted_at.date(), c.amount_cents) for c in result.candidates]
    assert got == [
        (date(2025, 12, 28), -450),
        (date(2026, 1, 5), 50000),
        (date(2026, 1, 10), -1763),
    ]
    assert result.format == "pdf"
    assert (rec.charges_cents, rec.credits_cents) == (2213, 50000)
    assert rec.difference_cents == 0


def test_missing_row_shows_as_difference():
    result, rec = statement_pdf.build_result([PAGE_1], _acct())
    assert rec.difference_cents == -1763  # the dropped grocery charge


def test_no_summary_means_unknown_difference_and_bad_rows_reported():
    page = {"transactions": [
        {"date": "01/02", "description": "X", "amount": 1, "kind": "charge"},
        {"date": "01/03", "description": "Y", "amount": 1, "kind": "mystery"},
        {"date": "nope", "description": "Z", "amount": 1, "kind": "charge"},
    ]}
    result, rec = statement_pdf.build_result([page], _acct(), today=date(2026, 3, 1))
    assert rec.difference_cents is None
    assert len(result.candidates) == 1
    assert len(result.errors) == 3  # two bad rows + no closing date
    assert any("closing date" in e for e in result.errors)


def test_malformed_model_output_is_skipped_not_fatal():
    pages = [
        ["not", "a", "dict"],
        {"summary": "oops", "transactions": "nope"},
        {"summary": None, "transactions": ["bad row", {"post_date": "01/02", "amount": 5, "kind": "charge"}]},
    ]
    result, _ = statement_pdf.build_result(pages, _acct(), today=date(2026, 3, 1))
    assert [c.amount_cents for c in result.candidates] == [-500]
    assert any("not an object" in e for e in result.errors)


def _pdf(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((50, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.asyncio
async def test_pdf_job_end_to_end(client: AsyncClient, monkeypatch):
    replies = iter([json.dumps(PAGE_1), json.dumps(PAGE_2)])
    calls = []

    async def fake_text(prompt, *, think=None, **_):
        assert think is False
        calls.append(prompt)
        return next(replies)

    monkeypatch.setattr(statement_pdf.ocr, "call_ollama_text", fake_text)
    acct = await _account(client, "Test Card", type_="credit")
    pdf = _pdf([
        "Previous balance 1,000.00  New balance 522.13\n12/28 ACME COFFEE 4.50\n01/05 PAYMENT 500.00",
        "Important legal notices about your account and arbitration and privacy." * 3,
        "01/10 TEST GROCERY 17.63\nMore filler text so the page clears the minimum.",
    ])
    resp = await client.post(
        "/api/import/statement-pdf",
        files={"file": ("statement.pdf", pdf, "application/pdf")},
        data={"account_id": str(acct["id"])},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    for _ in range(100):
        body = (await client.get(f"/api/import/statement-pdf/{job_id}")).json()
        if body["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert body["status"] == "done", body
    assert body["pages_total"] == 3
    assert len(calls) == 2  # legal-notice page skipped without a model call
    assert [c["amount_cents"] for c in body["result"]["candidates"]] == [-450, 50000, -1763]
    assert all(c["match_status"] == "new" for c in body["result"]["candidates"])
    assert body["reconciliation"]["difference_cents"] == 0


@pytest.mark.asyncio
async def test_pdf_job_rejects_non_pdf_and_unknown_job(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    resp = await client.post(
        "/api/import/statement-pdf",
        files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
        data={"account_id": str(acct["id"])},
    )
    assert resp.status_code == 415
    assert (await client.get("/api/import/statement-pdf/nope")).status_code == 404


@pytest.mark.asyncio
async def test_unreadable_page_does_not_fail_job(client: AsyncClient, monkeypatch):
    replies = iter(["no json here", "still no json", json.dumps(PAGE_2)])

    async def fake_text(prompt, *, think=None, **_):
        return next(replies)

    monkeypatch.setattr(statement_pdf.ocr, "call_ollama_text", fake_text)
    acct = await _account(client, "Test Card", type_="credit")
    pdf = _pdf(["12/28 ACME COFFEE 4.50", "01/10 TEST GROCERY 17.63"])
    job_id = (await client.post(
        "/api/import/statement-pdf",
        files={"file": ("statement.pdf", pdf, "application/pdf")},
        data={"account_id": str(acct["id"])},
    )).json()["job_id"]
    for _ in range(100):
        body = (await client.get(f"/api/import/statement-pdf/{job_id}")).json()
        if body["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert body["status"] == "done"
    assert [c["amount_cents"] for c in body["result"]["candidates"]] == [-1763]
    assert body["result"]["errors"][0] == "Page 1 couldn't be read by the model."
    assert not any("no json" in e for e in body["result"]["errors"])  # no reply text leaks
