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


def test_parse_transfer():
    from finance.services.quicken import _parse_transfer

    assert _parse_transfer("[Savings Account]") == ("Savings Account", "")
    assert _parse_transfer("Food:Groceries") == (None, "Food:Groceries")
    assert _parse_transfer("  [My IRA]  ") == ("My IRA", "")
    assert _parse_transfer("") == (None, "")


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
    # Pre-existing transaction same day, amount, AND description → strong duplicate
    resp = await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-05-15T08:00:00Z",
            "amount_cents": -5000,
            "description": "Costco",
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


async def test_likely_duplicate_vs_duplicate(client: AsyncClient):
    """amount+date match with different description → likely-duplicate, not duplicate."""
    acct = await _account(client, "Checking", quicken_id="LD-1")
    await client.post(
        "/api/transactions",
        json={
            "account_id": acct["id"],
            "posted_at": "2026-06-01T12:00:00Z",
            "amount_cents": -500,
            "description": "Coffee Shop A",
        },
    )

    qif = """\
!Account
NChecking
TBank
^
!Type:Bank
D06/01/2026
T-5.00
PCoffee Shop B
LDining
^
"""
    files = {"file": ("ld.qif", qif.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert len(cands) == 1
    assert cands[0]["match_status"] == "likely-duplicate"


async def test_fitid_dedup(client: AsyncClient):
    """Re-importing the same FITID is a definitive duplicate regardless of description."""
    acct = await _account(client, "Checking", quicken_id="FID-1")
    # First import
    qfx = """\
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD
<BANKACCTFROM><ACCTID>FID-1</ACCTID></BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><DTPOSTED>20260515<TRNAMT>-50.00<FITID>UNIQUE123<NAME>Costco</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
    files = {"file": ("f1.qfx", qfx.encode(), "application/x-ofx")}
    resp = await client.post("/api/import/qfx", files=files)
    parsed = resp.json()
    # Confirm to persist it
    confirm = await client.post("/api/import/confirm", json={
        "candidates": parsed["candidates"],
        "actions": [{"candidate_index": 0, "action": "create"}],
        "create_missing_categories": False,
    })
    assert confirm.json()["errors"] == []

    # Re-import same file — FITID should catch it
    files = {"file": ("f2.qfx", qfx.encode(), "application/x-ofx")}
    resp = await client.post("/api/import/qfx", files=files)
    cands = resp.json()["candidates"]
    assert cands[0]["match_status"] == "duplicate"


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


# ── QIF !Type:Cat parsing ──


QIF_WITH_CATEGORIES = """\
!Type:Cat
NFood & Dining
DRestaurants and groceries
E
^
NFood & Dining:Groceries
E
^
NIncome:Salary
I
T
RR286
^
NMisc
E
^
"""


async def test_qif_parses_category_definitions(client: AsyncClient):
    files = {"file": ("cats.qif", QIF_WITH_CATEGORIES.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    data = resp.json()

    cats = data["categories"]
    assert len(cats) == 4

    by_name = {c["name"]: c for c in cats}

    food = by_name["Food & Dining"]
    assert food["description"] == "Restaurants and groceries"
    assert food["is_income"] is False
    assert food["tax_related"] is False

    groceries = by_name["Food & Dining:Groceries"]
    assert groceries["is_income"] is False

    salary = by_name["Income:Salary"]
    assert salary["is_income"] is True
    assert salary["tax_related"] is True
    assert salary["tax_schedule"] == "R286"

    assert by_name["Misc"]["description"] is None
    assert data["candidates"] == []


# ── QIF !Type:Memorized parsing ──


QIF_WITH_MEMORIZED = """\
!Type:Memorized
KP
PCostco
LFood:Groceries
T-150.00
^
KD
PEmployer Inc
LIncome:Salary
T3500.00
^
KT
PTransfer to Savings
L[Savings Account]
T-500.00
^
KP
PNetflix
LEntertainment:Streaming
^
"""


async def test_qif_parses_memorized_rules(client: AsyncClient):
    files = {"file": ("mem.qif", QIF_WITH_MEMORIZED.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    data = resp.json()

    rules = data["memorized_rules"]
    assert len(rules) == 4

    costco = rules[0]
    assert costco["payee"] == "Costco"
    assert costco["category_path"] == "Food:Groceries"
    assert costco["amount_cents"] == -15000
    assert costco["kind"] == "payment"
    assert costco["transfer_account"] is None

    employer = rules[1]
    assert employer["payee"] == "Employer Inc"
    assert employer["kind"] == "deposit"
    assert employer["amount_cents"] == 350000

    transfer = rules[2]
    assert transfer["payee"] == "Transfer to Savings"
    assert transfer["transfer_account"] == "Savings Account"
    assert transfer["category_path"] == ""
    assert transfer["kind"] == "transfer"

    netflix = rules[3]
    assert netflix["payee"] == "Netflix"
    assert netflix["amount_cents"] is None


# ── Transfer notation and cleared status ──


QIF_WITH_TRANSFERS = """\
!Account
NMain Checking
TBank
^
!Type:Bank
D05/19/2026
T-500.00
PTransfer to Savings
L[Savings Account]
CX
^
D05/20/2026
T-12.34
PStarbucks
LDining
C*
^
D05/21/2026
T-25.00
PGas Station
LTransportation:Fuel
^
"""


async def test_qif_transfer_notation_and_cleared(client: AsyncClient):
    await _account(client, "Main Checking", quicken_id="Main Checking")
    files = {"file": ("xfer.qif", QIF_WITH_TRANSFERS.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    data = resp.json()

    cands = data["candidates"]
    assert len(cands) == 3

    xfer = cands[0]
    assert xfer["transfer_account"] == "Savings Account"
    assert xfer["cleared"] == "X"
    assert xfer["splits"] == []

    starbucks = cands[1]
    assert starbucks["transfer_account"] is None
    assert starbucks["cleared"] == "*"
    assert starbucks["splits"][0]["category_path"] == "Dining"

    gas = cands[2]
    assert gas["transfer_account"] is None
    assert gas["cleared"] is None
    assert gas["splits"][0]["category_path"] == "Transportation:Fuel"


# ── Mixed QIF with all section types ──


QIF_MIXED = """\
!Option:AutoSwitch
!Type:Cat
NFood
E
^
!Account
NChecking
TBank
^
!Type:Bank
D06/01/2026
T-10.00
PLunch
LFood
^
!Type:Memorized
KP
PLunch Spot
LFood
T-10.00
^
!Type:Security
NGoogle
SGOOG
^
"""


async def test_qif_mixed_sections(client: AsyncClient):
    await _account(client, "Checking", quicken_id="Checking")
    files = {"file": ("mix.qif", QIF_MIXED.encode(), "application/x-qif")}
    resp = await client.post("/api/import/qif", files=files)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Food"
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["description"] == "Lunch"
    assert len(data["memorized_rules"]) == 1
    assert data["memorized_rules"][0]["payee"] == "Lunch Spot"


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
