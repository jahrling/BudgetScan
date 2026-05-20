from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from finance.db import get_session
from finance.main import app
from finance.models import Base


@pytest.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "test", "password": "test"})
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def _account(client: AsyncClient, name: str, quicken_id: str | None = None,
                   currency: str = "USD", type_: str = "checking") -> dict:
    resp = await client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "quicken_id": quicken_id, "currency": currency},
    )
    assert resp.status_code == 201
    return resp.json()


async def _category(client: AsyncClient, name: str, parent_id: int | None = None) -> dict:
    resp = await client.post(
        "/api/categories", json={"name": name, "parent_id": parent_id}
    )
    assert resp.status_code == 201
    return resp.json()


# ── Money helper ──


def test_amount_to_cents_roundtrip():
    from finance.services.quicken import _amount_to_cents, _cents_to_amount

    assert _amount_to_cents("12.34") == 1234
    assert _amount_to_cents("-12.34") == -1234
    assert _amount_to_cents("0.05") == 5
    assert _amount_to_cents("1,234.56") == 123456
    assert _amount_to_cents("100") == 10000
    assert _cents_to_amount(1234) == "12.34"
    assert _cents_to_amount(-50) == "-0.50"
    assert _cents_to_amount(0) == "0.00"


# ── QFX multi-account import ──


QFX_TWO_ACCOUNTS = """\
OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD
<BANKACCTFROM><ACCTID>CHECKING-123</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260515120000<TRNAMT>-50.00<FITID>F1<NAME>Costco</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260516<TRNAMT>-12.34<FITID>F2<NAME>Starbucks</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1>
<CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS>
<CURDEF>USD
<CCACCTFROM><ACCTID>CARD-999</ACCTID></CCACCTFROM>
<BANKTRANLIST>
<STMTTRN><DTPOSTED>20260517<TRNAMT>-200.00<FITID>F3<NAME>Amazon</STMTTRN>
</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1>
</OFX>
"""


async def test_qfx_multi_account_import(client: AsyncClient):
    await _account(client, "Checking", quicken_id="CHECKING-123")
    # CARD-999 is intentionally not mapped to surface as unmapped.

    files = {"file": ("statement.qfx", QFX_TWO_ACCOUNTS.encode(), "application/x-ofx")}
    resp = await client.post("/api/import/qfx", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) == 3
    # Costco and Starbucks should be mapped, Amazon should not.
    by_desc = {c["description"]: c for c in data["candidates"]}
    assert by_desc["Costco"]["account_id"] is not None
    assert by_desc["Starbucks"]["amount_cents"] == -1234
    assert by_desc["Amazon"]["account_id"] is None
    assert "CARD-999" in data["unmapped_accounts"]


# ── Currency mismatch hard-fails the statement ──


QFX_CURRENCY_MISMATCH = """\
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>EUR
<BANKACCTFROM><ACCTID>EU-001</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><DTPOSTED>20260515<TRNAMT>-10.00<FITID>X1<NAME>Cafe</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


async def test_qfx_currency_mismatch_skips_statement(client: AsyncClient):
    await _account(client, "USD Account", quicken_id="EU-001", currency="USD")
    files = {"file": ("eur.qfx", QFX_CURRENCY_MISMATCH.encode(), "application/x-ofx")}
    resp = await client.post("/api/import/qfx", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidates"] == []
    assert any("Currency mismatch" in e for e in data["errors"])


# ── Duplicate detection ──


async def test_qfx_duplicate_detection(client: AsyncClient):
    acct = await _account(client, "Checking", quicken_id="DUP-1")
    # Pre-existing transaction same day & amount
    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-15T08:00:00Z",
            "amount_cents": -5000,
        },
    )
    assert resp.status_code == 201
    existing_id = resp.json()["id"]

    qfx = """\
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD
<BANKACCTFROM><ACCTID>DUP-1</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><DTPOSTED>20260515<TRNAMT>-50.00<FITID>D1<NAME>Costco</STMTTRN>
<STMTTRN><DTPOSTED>20260516<TRNAMT>-25.00<FITID>D2<NAME>Target</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
    files = {"file": ("d.qfx", qfx.encode(), "application/x-ofx")}
    resp = await client.post("/api/import/qfx", files=files)
    cands = resp.json()["candidates"]
    by_desc = {c["description"]: c for c in cands}
    assert by_desc["Costco"]["match_status"] == "duplicate"
    assert by_desc["Costco"]["match_transaction_id"] == existing_id
    assert by_desc["Target"]["match_status"] == "new"


# ── QIF round-trip: import → export → import → no diff ──


QIF_INPUT = """\
!Account
NMain Checking
TBank
^
!Type:Bank
D05/19/2026
T-50.00
PCostco
LFood:Groceries
SFood:Groceries
$-30.00
SHousehold
$-20.00
^
D05/20/2026
T-12.34
PStarbucks
LDining
^
"""


async def test_qif_roundtrip_preserves_splits(client: AsyncClient):
    acct = await _account(client, "Main Checking", quicken_id="Main Checking")
    # Intentionally don't pre-create — let create_missing_categories=True
    # materialize "Food:Groceries", "Household", and "Dining" as flat paths.

    # ── Import ──
    files = {"file": ("in.qif", QIF_INPUT.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    parsed = resp.json()
    assert len(parsed["candidates"]) == 2
    assert parsed["candidates"][0]["amount_cents"] == -5000
    assert len(parsed["candidates"][0]["splits"]) == 2

    # ── Confirm with create_missing_categories=True so colon paths resolve ──
    actions = [
        {"candidate_index": i, "action": "create"}
        for i in range(len(parsed["candidates"]))
    ]
    confirm_body = {
        "candidates": parsed["candidates"],
        "actions": actions,
        "create_missing_categories": True,
    }
    resp = await client.post("/api/import/confirm", json=confirm_body)
    assert resp.status_code == 200, resp.text
    confirm = resp.json()
    assert confirm["errors"] == []
    assert len(confirm["created_ids"]) == 2

    # ── Export back to QIF ──
    resp = await client.get(
        f"/api/export/qif?accounts={acct['id']}"
    )
    assert resp.status_code == 200
    exported = resp.text
    assert "!Account" in exported
    assert "!Type:Bank" in exported
    assert "SFood:Groceries" in exported
    assert "$-30.00" in exported
    assert "$-20.00" in exported

    # ── Re-import the exported QIF — should produce equivalent candidates ──
    files = {"file": ("rt.qif", exported.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    second = resp.json()
    assert len(second["candidates"]) == 2

    def normalize(c):
        return (
            c["amount_cents"],
            c["description"],
            sorted([(s["category_path"], s["amount_cents"]) for s in c["splits"]]),
        )

    a = sorted(normalize(c) for c in parsed["candidates"])
    b = sorted(normalize(c) for c in second["candidates"])
    assert a == b


# ── Confirm: skip / create / errors are per-row ──


async def test_confirm_actions(client: AsyncClient):
    acct = await _account(client, "C", quicken_id="C-1")
    qfx = """\
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD
<BANKACCTFROM><ACCTID>C-1</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><DTPOSTED>20260515<TRNAMT>-10.00<FITID>A1<NAME>One</STMTTRN>
<STMTTRN><DTPOSTED>20260515<TRNAMT>-20.00<FITID>A2<NAME>Two</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
    files = {"file": ("x.qfx", qfx.encode(), "application/x-ofx")}
    parsed = (await client.post("/api/import/qfx", files=files)).json()
    body = {
        "candidates": parsed["candidates"],
        "actions": [
            {"candidate_index": 0, "action": "create"},
            {"candidate_index": 1, "action": "skip"},
        ],
        "create_missing_categories": False,
    }
    resp = await client.post("/api/import/confirm", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["created_ids"]) == 1
    assert data["skipped"] == 1
    assert data["errors"] == []
