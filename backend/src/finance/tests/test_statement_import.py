"""Statement upload: CSV layouts, sign handling, QFX with a forced account.

All fixtures are synthetic (see SECURITY.md §4).
"""

import pytest
from httpx import AsyncClient

from finance.tests.test_quicken import _account, client  # noqa: F401  (fixture)


async def _upload(
    client: AsyncClient,
    account_id: int,
    content: str | bytes,
    filename: str = "activity.csv",
    invert: bool | None = None,
):
    data = {"account_id": str(account_id)}
    if invert is not None:
        data["invert"] = "true" if invert else "false"
    body = content.encode() if isinstance(content, str) else content
    return await client.post(
        "/api/import/statement",
        files={"file": (filename, body, "text/csv")},
        data=data,
    )


# Charges negative, payments positive; posted date should win over txn date.
SIGNED_CSV = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
01/14/2026,01/15/2026,ACME COFFEE,Food & Drink,Sale,-4.50,
01/15/2026,01/16/2026,TEST GROCERY,Groceries,Sale,-82.13,
01/20/2026,01/20/2026,AUTOPAY PAYMENT,,Payment,500.00,
"""

# Charges positive, payments negative — needs inversion.
POSITIVE_CHARGES_CSV = """Date,Description,Amount
01/15/2026,ACME COFFEE,4.50
01/16/2026,TEST GROCERY,"1,082.13"
01/17/2026,TEST BOOKSTORE,12.00
01/20/2026,ONLINE PAYMENT - THANK YOU,-500.00
"""

# Separate debit/credit columns, with a preamble before the header and
# a credit that carries its own minus sign.
SPLIT_CSV = """Account summary
Statement period,01/01/2026 - 01/31/2026

Status,Date,Description,Debit,Credit
Cleared,2026-01-15,ACME COFFEE,4.50,
Cleared,2026-01-20,PAYMENT RECEIVED,,-500.00
"""

DIRECTION_CSV = """Posting Date,Payee,Amount,Credit Debit Indicator
01/15/2026 00:00:00,ACME COFFEE,4.50,Debit
01/16/2026 00:00:00,REFUND TEST STORE,10.00,Credit
01/17/2026 00:00:00,TEST GROCERY,20.00,Debit
"""

QFX = """OFXHEADER:100
DATA:OFXSGML

<OFX>
<CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS>
<CURDEF>USD
<CCACCTFROM><ACCTID>CARD-SYNTH-0001</CCACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260115<TRNAMT>-4.50<FITID>F1<NAME>ACME COFFEE</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260120<TRNAMT>500.00<FITID>F2<NAME>PAYMENT</STMTTRN>
</BANKTRANLIST>
</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1>
</OFX>
"""


@pytest.mark.asyncio
async def test_signed_csv_uses_post_date(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    resp = await _upload(client, acct["id"], SIGNED_CSV)
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "csv"
    assert body["inverted"] is False
    assert body["columns"]["date"] == "Post Date"
    cands = body["candidates"]
    assert [c["amount_cents"] for c in cands] == [-450, -8213, 50000]
    assert cands[0]["posted_at"].startswith("2026-01-15")
    assert all(c["account_id"] == acct["id"] for c in cands)
    assert body["unmapped_accounts"] == []


@pytest.mark.asyncio
async def test_positive_charges_auto_invert_and_override(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    body = (await _upload(client, acct["id"], POSITIVE_CHARGES_CSV)).json()
    assert body["inverted"] is True
    assert [c["amount_cents"] for c in body["candidates"]] == [-450, -108213, -1200, 50000]

    body = (await _upload(client, acct["id"], POSITIVE_CHARGES_CSV, invert=False)).json()
    assert body["inverted"] is False
    assert body["candidates"][0]["amount_cents"] == 450


@pytest.mark.asyncio
async def test_split_debit_credit_columns_with_preamble(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    body = (await _upload(client, acct["id"], SPLIT_CSV)).json()
    assert body["errors"] == []
    assert body["inverted"] is None
    assert [c["amount_cents"] for c in body["candidates"]] == [-450, 50000]


@pytest.mark.asyncio
async def test_direction_column(client: AsyncClient):
    acct = await _account(client, "Test Checking")
    body = (await _upload(client, acct["id"], DIRECTION_CSV)).json()
    assert body["inverted"] is None
    assert body["columns"]["direction"] == "Credit Debit Indicator"
    assert [c["amount_cents"] for c in body["candidates"]] == [-450, 1000, -2000]


@pytest.mark.asyncio
async def test_bad_rows_reported_not_fatal(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    csv = SIGNED_CSV + "Total,,,,,,\n"
    body = (await _upload(client, acct["id"], csv)).json()
    assert len(body["candidates"]) == 3
    assert len(body["errors"]) == 1


@pytest.mark.asyncio
async def test_no_header_is_an_error(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    body = (await _upload(client, acct["id"], "foo,bar\n1,2\n")).json()
    assert body["candidates"] == []
    assert body["errors"]


@pytest.mark.asyncio
async def test_qfx_forced_to_chosen_account(client: AsyncClient):
    # Account has no quicken_id, so plain QFX import would leave it unmapped.
    acct = await _account(client, "Test Card", type_="credit")
    body = (await _upload(client, acct["id"], QFX, filename="activity.qfx")).json()
    assert body["format"] == "ofx"
    assert body["unmapped_accounts"] == []
    assert [c["amount_cents"] for c in body["candidates"]] == [-450, 50000]
    assert all(c["account_id"] == acct["id"] for c in body["candidates"])


@pytest.mark.asyncio
async def test_pdf_rejected(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    resp = await _upload(client, acct["id"], b"%PDF-1.7 synthetic", filename="statement.pdf")
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_unknown_account_404(client: AsyncClient):
    resp = await _upload(client, 9999, SIGNED_CSV)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_confirm_then_reupload_flags_duplicates(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    body = (await _upload(client, acct["id"], SIGNED_CSV)).json()
    cands = body["candidates"]
    resp = await client.post(
        "/api/import/confirm",
        json={
            "candidates": cands,
            "actions": [{"candidate_index": i, "action": "create"} for i in range(len(cands))],
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["created_ids"]) == 3

    again = (await _upload(client, acct["id"], SIGNED_CSV)).json()
    assert {c["match_status"] for c in again["candidates"]} == {"duplicate"}


@pytest.mark.asyncio
async def test_cr_suffix_is_explicit_and_not_inverted(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    csv = """Date,Description,Amount
01/15/2026,ACME COFFEE,45.00
01/16/2026,TEST GROCERY,20.00
01/17/2026,TEST STORE REFUND,12.34 CR
01/18/2026,TEST FEE,3.00 DR
"""
    body = (await _upload(client, acct["id"], csv)).json()
    assert body["inverted"] is True
    assert [c["amount_cents"] for c in body["candidates"]] == [-4500, -2000, 1234, -300]


@pytest.mark.asyncio
async def test_blank_debit_and_credit_is_row_error(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    csv = "Date,Description,Debit,Credit\n2026-01-15,ACME COFFEE,4.50,\n2026-01-16,NOTHING,,\n"
    body = (await _upload(client, acct["id"], csv)).json()
    assert [c["amount_cents"] for c in body["candidates"]] == [-450]
    assert len(body["errors"]) == 1


@pytest.mark.asyncio
async def test_qfx_without_acctid_still_assigned(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    qfx = QFX.replace("<CCACCTFROM><ACCTID>CARD-SYNTH-0001</CCACCTFROM>\n", "")
    body = (await _upload(client, acct["id"], qfx, filename="activity.qfx")).json()
    assert len(body["candidates"]) == 2
    assert all(c["account_id"] == acct["id"] for c in body["candidates"])


@pytest.mark.asyncio
async def test_multi_account_qfx_rejected(client: AsyncClient):
    acct = await _account(client, "Test Card", type_="credit")
    second = QFX.split("<OFX>", 1)[1].rsplit("</OFX>", 1)[0].replace("CARD-SYNTH-0001", "CARD-SYNTH-0002")
    qfx = QFX.replace("</OFX>", second + "</OFX>")
    body = (await _upload(client, acct["id"], qfx, filename="activity.qfx")).json()
    assert body["candidates"] == []
    assert any("several accounts" in e for e in body["errors"])
