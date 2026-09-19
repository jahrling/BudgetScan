"""Investment domain router — plan §5 endpoints.

Phase 3 scope: CRUD for securities/transactions, manual snapshots, lot rebuild,
QIF import, benchmark CSV upload, and settings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.investment_settings import InvestmentSettings
from finance.models.investment_transaction import InvestmentTransaction
from finance.models.lot import Lot, LotDisposal
from finance.models.position_snapshot import PositionSnapshot
from finance.models.security import PriceHistory, Security
from finance.schemas.investment import (
    HoldingDetailRead,
    HoldingSummaryRead,
    InvestmentSettingsRead,
    InvestmentSettingsUpdate,
    InvestmentTransactionCreate,
    InvestmentTransactionRead,
    InvestmentTransactionUpdate,
    LotRead,
    OverviewRead,
    PriceHistoryRead,
    PositionSnapshotCreate,
    PositionSnapshotRead,
    SecurityCreate,
    SecurityRead,
    SecurityUpdate,
)
from finance.services.investment_analytics import (
    get_holdings,
    get_holding_detail,
    get_overview,
)
from finance.services.investment_import import (
    InvestmentParseResult,
    parse_investment_qif,
    parse_price_csv,
)
from finance.services.lot_engine import TxnInput, rebuild_lots

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(
    prefix="/api/investments",
    tags=["investments"],
    dependencies=[Depends(current_user)],
)


# ── Securities ─────────────────────────────────────────────────────────────


@router.get("/securities", response_model=list[SecurityRead])
async def list_securities(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Security).order_by(Security.name))
    return list(result.scalars().all())


@router.post("/securities", response_model=SecurityRead, status_code=201)
async def create_security(
    data: SecurityCreate, session: AsyncSession = Depends(get_session)
):
    security = Security(**data.model_dump())
    session.add(security)
    await session.flush()
    await session.commit()
    await session.refresh(security)
    return security


@router.patch("/securities/{security_id}", response_model=SecurityRead)
async def update_security(
    security_id: int,
    data: SecurityUpdate,
    session: AsyncSession = Depends(get_session),
):
    security = await session.get(Security, security_id)
    if security is None:
        raise HTTPException(404, "Security not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(security, k, v)
    await session.commit()
    await session.refresh(security)
    return security


# ── Aggregate views ───────────────────────────────────────────────────────


@router.get("/overview", response_model=OverviewRead)
async def overview(session: AsyncSession = Depends(get_session)):
    data = await get_overview(session)
    return OverviewRead(
        total_value_cents=data.total_value_cents,
        invested_capital_cents=data.invested_capital_cents,
        cost_basis_cents=data.cost_basis_cents,
        total_gain_cents=data.total_gain_cents,
        income_cents=data.income_cents,
        realized_gain_cents=data.realized_gain_cents,
        accounts=[
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "value_cents": a.value_cents,
                "invested_capital_cents": a.invested_capital_cents,
                "cost_basis_cents": a.cost_basis_cents,
                "gain_cents": a.gain_cents,
                "income_cents": a.income_cents,
                "holdings_count": a.holdings_count,
            }
            for a in data.accounts
        ],
        holdings_count=data.holdings_count,
    )


@router.get("/holdings", response_model=list[HoldingSummaryRead])
async def list_holdings(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    rows = await get_holdings(session, account_id)
    return [
        HoldingSummaryRead(
            security_id=h.security_id,
            security_name=h.security_name,
            symbol=h.symbol,
            security_type=h.security_type,
            account_id=h.account_id,
            account_name=h.account_name,
            account_type=h.account_type,
            quantity_micros=h.quantity_micros,
            latest_price_micros=h.latest_price_micros,
            latest_price_date=h.latest_price_date,
            market_value_cents=h.market_value_cents,
            cost_basis_cents=h.cost_basis_cents,
            invested_capital_cents=h.invested_capital_cents,
            unrealized_gain_cents=h.unrealized_gain_cents,
            income_cents=h.income_cents,
            realized_gain_cents=h.realized_gain_cents,
        )
        for h in rows
    ]


@router.get("/holdings/{security_id}", response_model=HoldingDetailRead)
async def holding_detail(
    security_id: int,
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    detail = await get_holding_detail(session, security_id, account_id)
    if detail is None:
        raise HTTPException(404, "Security not found")
    return HoldingDetailRead(
        security=detail.security,
        account_id=detail.account_id,
        account_name=detail.account_name,
        quantity_micros=detail.quantity_micros,
        latest_price_micros=detail.latest_price_micros,
        latest_price_date=detail.latest_price_date,
        market_value_cents=detail.market_value_cents,
        cost_basis_cents=detail.cost_basis_cents,
        invested_capital_cents=detail.invested_capital_cents,
        unrealized_gain_cents=detail.unrealized_gain_cents,
        income_cents=detail.income_cents,
        realized_gain_cents=detail.realized_gain_cents,
        lots=[
            {
                **{
                    "id": lwd.lot.id,
                    "account_id": lwd.lot.account_id,
                    "security_id": lwd.lot.security_id,
                    "opened_at": lwd.lot.opened_at,
                    "opened_by_txn_id": lwd.lot.opened_by_txn_id,
                    "quantity_micros_original": lwd.lot.quantity_micros_original,
                    "quantity_micros_remaining": lwd.lot.quantity_micros_remaining,
                    "cost_basis_cents": lwd.lot.cost_basis_cents,
                    "is_reinvestment": lwd.lot.is_reinvestment,
                    "source": lwd.lot.source,
                    "created_at": lwd.lot.created_at,
                    "updated_at": lwd.lot.updated_at,
                },
                "disposals": [
                    {
                        "id": d.id,
                        "lot_id": d.lot_id,
                        "sell_txn_id": d.sell_txn_id,
                        "quantity_micros": d.quantity_micros,
                        "proceeds_cents": d.proceeds_cents,
                        "basis_cents": d.basis_cents,
                        "realized_gain_cents": d.realized_gain_cents,
                        "term": d.term,
                    }
                    for d in lwd.disposals
                ],
            }
            for lwd in detail.lots
        ],
        transactions=detail.transactions,
    )


# ── Investment transactions ────────────────────────────────────────────────


@router.get("/transactions", response_model=list[InvestmentTransactionRead])
async def list_investment_transactions(
    account_id: int | None = None,
    security_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(InvestmentTransaction).order_by(InvestmentTransaction.trade_date.desc())
    if account_id is not None:
        q = q.where(InvestmentTransaction.account_id == account_id)
    if security_id is not None:
        q = q.where(InvestmentTransaction.security_id == security_id)
    result = await session.execute(q)
    return list(result.scalars().all())


@router.post("/transactions", response_model=InvestmentTransactionRead, status_code=201)
async def create_investment_transaction(
    data: InvestmentTransactionCreate,
    session: AsyncSession = Depends(get_session),
):
    txn = InvestmentTransaction(**data.model_dump())
    session.add(txn)
    await session.flush()
    await session.commit()
    await session.refresh(txn)
    return txn


@router.patch("/transactions/{txn_id}", response_model=InvestmentTransactionRead)
async def update_investment_transaction(
    txn_id: int,
    data: InvestmentTransactionUpdate,
    session: AsyncSession = Depends(get_session),
):
    txn = await session.get(InvestmentTransaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Investment transaction not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(txn, k, v)
    await session.commit()
    await session.refresh(txn)
    return txn


@router.delete("/transactions/{txn_id}", status_code=204)
async def delete_investment_transaction(
    txn_id: int, session: AsyncSession = Depends(get_session)
):
    txn = await session.get(InvestmentTransaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Investment transaction not found")
    await session.delete(txn)
    await session.commit()


# ── Position snapshots ─────────────────────────────────────────────────────


@router.get("/snapshots", response_model=list[PositionSnapshotRead])
async def list_snapshots(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(PositionSnapshot).order_by(PositionSnapshot.as_of.desc())
    if account_id is not None:
        q = q.where(PositionSnapshot.account_id == account_id)
    result = await session.execute(q)
    return list(result.scalars().all())


@router.post("/snapshots", response_model=list[PositionSnapshotRead], status_code=201)
async def create_snapshots(
    data: list[PositionSnapshotCreate],
    session: AsyncSession = Depends(get_session),
):
    snapshots = []
    for item in data:
        snap = PositionSnapshot(**item.model_dump())
        session.add(snap)
        snapshots.append(snap)
    await session.flush()
    await session.commit()
    for snap in snapshots:
        await session.refresh(snap)
    return snapshots


# ── Lots ───────────────────────────────────────────────────────────────────


@router.get("/lots", response_model=list[LotRead])
async def list_lots(
    account_id: int | None = None,
    security_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(Lot).order_by(Lot.opened_at)
    if account_id is not None:
        q = q.where(Lot.account_id == account_id)
    if security_id is not None:
        q = q.where(Lot.security_id == security_id)
    result = await session.execute(q)
    return list(result.scalars().all())


class LotRebuildResponse(BaseModel):
    holdings_processed: int
    lots_created: int
    disposals_created: int


@router.post("/lots/rebuild", response_model=LotRebuildResponse)
async def rebuild_lots_endpoint(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Replay the ledger and rebuild derived lots for all (account, security) pairs."""
    # Delete existing derived lots
    del_q = delete(Lot).where(Lot.source == "derived")
    if account_id is not None:
        del_q = del_q.where(Lot.account_id == account_id)
    await session.execute(del_q)
    await session.flush()

    # Find all (account_id, security_id) pairs with transactions
    txn_q = select(
        InvestmentTransaction.account_id,
        InvestmentTransaction.security_id,
    ).where(
        InvestmentTransaction.security_id.is_not(None),
    ).distinct()

    if account_id is not None:
        txn_q = txn_q.where(InvestmentTransaction.account_id == account_id)

    pairs = (await session.execute(txn_q)).all()

    # Check which pairs have statement lots (those take precedence)
    statement_q = select(
        Lot.account_id, Lot.security_id
    ).where(Lot.source == "statement").distinct()
    statement_pairs = set((await session.execute(statement_q)).all())

    total_lots = 0
    total_disposals = 0
    holdings_processed = 0

    for acct_id, sec_id in pairs:
        if (acct_id, sec_id) in statement_pairs:
            continue

        security = await session.get(Security, sec_id)
        if security and security.is_cash_equivalent:
            continue

        holdings_processed += 1

        txns_result = await session.execute(
            select(InvestmentTransaction)
            .where(
                InvestmentTransaction.account_id == acct_id,
                InvestmentTransaction.security_id == sec_id,
            )
            .order_by(InvestmentTransaction.trade_date, InvestmentTransaction.id)
        )
        txns = list(txns_result.scalars().all())

        inputs = [
            TxnInput(
                id=t.id,
                action=t.action,
                trade_date=t.trade_date,
                quantity_micros=t.quantity_micros,
                price_micros=t.price_micros,
                amount_cents=t.amount_cents,
                fee_cents=t.fee_cents,
            )
            for t in txns
        ]

        lot_result = rebuild_lots(inputs)

        for i, lr in enumerate(lot_result.lots):
            lot = Lot(
                account_id=acct_id,
                security_id=sec_id,
                opened_at=lr.opened_at,
                opened_by_txn_id=lr.opened_by_txn_id,
                quantity_micros_original=lr.quantity_micros_original,
                quantity_micros_remaining=lr.quantity_micros_remaining,
                cost_basis_cents=lr.cost_basis_cents,
                is_reinvestment=lr.is_reinvestment,
                source="derived",
            )
            session.add(lot)
            await session.flush()

            for dr in lot_result.disposals:
                if dr.lot_index == i:
                    disposal = LotDisposal(
                        lot_id=lot.id,
                        sell_txn_id=dr.sell_txn_id,
                        quantity_micros=dr.quantity_micros,
                        proceeds_cents=dr.proceeds_cents,
                        basis_cents=dr.basis_cents,
                        realized_gain_cents=dr.realized_gain_cents,
                        term=dr.term,
                    )
                    session.add(disposal)
                    total_disposals += 1

            total_lots += 1

    await session.commit()

    return LotRebuildResponse(
        holdings_processed=holdings_processed,
        lots_created=total_lots,
        disposals_created=total_disposals,
    )


# ── Price history ──────────────────────────────────────────────────────────


@router.get("/prices", response_model=list[PriceHistoryRead])
async def list_prices(
    security_id: int,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(PriceHistory)
        .where(PriceHistory.security_id == security_id)
        .order_by(PriceHistory.date)
    )
    return list(result.scalars().all())


@router.post("/prices/upload")
async def upload_prices(
    security_id: int,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
):
    """Upload a CSV of prices for a security (Yahoo Finance / Stooq format)."""
    security = await session.get(Security, security_id)
    if security is None:
        raise HTTPException(404, "Security not found")

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (10 MB limit)")
    content = raw.decode("utf-8", errors="replace")
    csv_result = parse_price_csv(content, security.name)

    if csv_result.errors:
        raise HTTPException(400, detail={"errors": csv_result.errors})

    rows_written = 0
    for pc in csv_result.prices:
        existing = await session.execute(
            select(PriceHistory).where(
                PriceHistory.security_id == security_id,
                PriceHistory.date == pc.date,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        session.add(PriceHistory(
            security_id=security_id,
            date=pc.date,
            close_micros=pc.price_micros,
            source="csv_upload",
        ))
        rows_written += 1

    await session.commit()
    return {"rows_written": rows_written, "total_parsed": len(csv_result.prices)}


# ── QIF investment import ──────────────────────────────────────────────────


class QIFImportResponse(BaseModel):
    transactions_imported: int
    securities_created: int
    accounts_created: int
    prices_imported: int
    skipped_duplicate: int
    skipped_other: int
    skipped_banking: int
    errors: list[str]


@router.post("/import/qif", response_model=QIFImportResponse)
async def import_investment_qif(
    file: UploadFile,
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Import investment transactions from a QIF file.

    When ``account_id`` is provided, all transactions are assigned to that
    account.  When omitted, accounts are auto-discovered from QIF !Account
    blocks and created if they don't already exist.
    """
    from finance.models.account import Account

    fallback_account: Account | None = None
    if account_id is not None:
        fallback_account = await session.get(Account, account_id)
        if fallback_account is None:
            raise HTTPException(404, "Account not found")

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (10 MB limit)")
    content = raw.decode("cp1252", errors="replace")
    parsed: InvestmentParseResult = parse_investment_qif(content)

    # 1. Resolve / auto-create accounts from QIF !Account blocks
    account_map: dict[str, int] = {}
    accounts_created = 0

    existing_accts = (await session.execute(select(Account))).scalars().all()
    for acct in existing_accts:
        account_map[acct.name] = acct.id

    for pa in parsed.accounts:
        if pa.name not in account_map:
            acct = Account(name=pa.name, type="brokerage", quicken_id=pa.name)
            session.add(acct)
            await session.flush()
            account_map[acct.name] = acct.id
            accounts_created += 1

    def resolve_account_id(account_key: str) -> int | None:
        if account_key and account_key in account_map:
            return account_map[account_key]
        if fallback_account is not None:
            return fallback_account.id
        return None

    # 2. Create/resolve securities by name
    security_map: dict[str, Security] = {}
    existing_secs = await session.execute(select(Security))
    for sec in existing_secs.scalars().all():
        security_map[sec.name] = sec

    securities_created = 0
    for sc in parsed.securities:
        if sc.name not in security_map:
            sec = Security(
                name=sc.name,
                symbol=sc.symbol,
                security_type=sc.security_type,
            )
            session.add(sec)
            await session.flush()
            security_map[sc.name] = sec
            securities_created += 1

    for cand in parsed.candidates:
        if cand.security_name and cand.security_name not in security_map:
            sec = Security(name=cand.security_name, security_type="other")
            session.add(sec)
            await session.flush()
            security_map[cand.security_name] = sec
            securities_created += 1

    # 3. Import prices
    prices_imported = 0
    for pc in parsed.prices:
        sec = security_map.get(pc.security_name)
        if sec is None:
            continue
        existing = await session.execute(
            select(PriceHistory).where(
                PriceHistory.security_id == sec.id,
                PriceHistory.date == pc.date,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        session.add(PriceHistory(
            security_id=sec.id,
            date=pc.date,
            close_micros=pc.price_micros,
            source="qif",
        ))
        prices_imported += 1

    # 4. Import transactions (with dedup on external_id)
    txns_imported = 0
    skipped_duplicate = 0
    skipped_no_account = 0
    for cand in parsed.candidates:
        resolved_id = resolve_account_id(cand.account_key)
        if resolved_id is None:
            skipped_no_account += 1
            continue

        security_id = None
        if cand.security_name:
            sec = security_map.get(cand.security_name)
            if sec:
                security_id = sec.id

        if cand.external_id:
            existing = await session.execute(
                select(InvestmentTransaction).where(
                    InvestmentTransaction.account_id == resolved_id,
                    InvestmentTransaction.external_id == cand.external_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                skipped_duplicate += 1
                continue

        txn = InvestmentTransaction(
            account_id=resolved_id,
            security_id=security_id,
            action=cand.action,
            trade_date=cand.trade_date,
            quantity_micros=cand.quantity_micros,
            price_micros=cand.price_micros,
            amount_cents=cand.amount_cents,
            fee_cents=cand.fee_cents,
            source="qif",
            external_id=cand.external_id,
            memo=cand.memo,
        )
        session.add(txn)
        txns_imported += 1

    if skipped_no_account > 0:
        parsed.errors.append(
            f"{skipped_no_account} transaction(s) skipped: no account could be determined"
        )

    await session.commit()

    return QIFImportResponse(
        transactions_imported=txns_imported,
        securities_created=securities_created,
        accounts_created=accounts_created,
        prices_imported=prices_imported,
        skipped_duplicate=skipped_duplicate,
        skipped_other=parsed.skipped_count,
        skipped_banking=parsed.skipped_banking_count,
        errors=parsed.errors,
    )


# ── Settings ───────────────────────────────────────────────────────────────


async def _get_or_create_settings(session: AsyncSession) -> InvestmentSettings:
    result = await session.execute(select(InvestmentSettings).where(InvestmentSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = InvestmentSettings(id=1)
        session.add(settings)
        await session.flush()
    return settings


@router.get("/settings", response_model=InvestmentSettingsRead)
async def get_settings(session: AsyncSession = Depends(get_session)):
    return await _get_or_create_settings(session)


@router.patch("/settings", response_model=InvestmentSettingsRead)
async def update_settings(
    data: InvestmentSettingsUpdate,
    session: AsyncSession = Depends(get_session),
):
    settings = await _get_or_create_settings(session)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(settings, k, v)
    await session.commit()
    await session.refresh(settings)
    return settings
