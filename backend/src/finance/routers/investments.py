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
    get_performance,
)
from finance.services.investment_import import (
    HoldingsCSVResult,
    InvestmentParseResult,
    parse_holdings_csv,
    parse_investment_qif,
    parse_price_csv,
)
from finance.services.market_data import fetch_risk_free_rate_bps, fetch_sp500_prices
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


# ── Performance / risk analytics ──────────────────────────────────────────


class RiskMetricsResponse(BaseModel):
    beta: float
    alpha_monthly: float
    alpha_annualized: float
    r_squared: float
    volatility_annualized: float
    sharpe_ratio: float
    max_drawdown: float
    n_months: int


class MonthlyReturnResponse(BaseModel):
    date: str
    portfolio: float
    benchmark: float | None


class DecompositionResponse(BaseModel):
    contributions_cents: int
    income_cents: int
    appreciation_cents: int


class PerformanceResponse(BaseModel):
    risk_metrics: RiskMetricsResponse | None
    portfolio_return: float | None
    benchmark_return: float | None
    xirr_return: float | None
    decomposition: DecompositionResponse | None
    monthly_returns: list[MonthlyReturnResponse]
    benchmark_name: str | None
    benchmark_symbol: str | None
    has_benchmark: bool
    error: str | None = None


@router.get("/performance", response_model=PerformanceResponse)
async def performance(
    account_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    data = await get_performance(session, account_id)
    return PerformanceResponse(
        risk_metrics=RiskMetricsResponse(**vars(data.risk_metrics)) if data.risk_metrics else None,
        portfolio_return=data.portfolio_return,
        benchmark_return=data.benchmark_return,
        xirr_return=data.xirr_return,
        decomposition=DecompositionResponse(
            contributions_cents=data.decomposition.contributions_cents,
            income_cents=data.decomposition.income_cents,
            appreciation_cents=data.decomposition.appreciation_cents,
        ) if data.decomposition else None,
        monthly_returns=[
            MonthlyReturnResponse(date=m.date, portfolio=m.portfolio, benchmark=m.benchmark)
            for m in data.monthly_returns
        ],
        benchmark_name=data.benchmark_name,
        benchmark_symbol=data.benchmark_symbol,
        has_benchmark=data.has_benchmark,
        error=data.error,
    )


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

    _BANKING_TYPES = {"checking", "savings", "credit_card", "cash"}

    existing_accts = (await session.execute(select(Account))).scalars().all()
    existing_by_name: dict[str, Account] = {}
    for acct in existing_accts:
        account_map[acct.name] = acct.id
        existing_by_name[acct.name] = acct

    for pa in parsed.accounts:
        if pa.name in existing_by_name:
            acct = existing_by_name[pa.name]
            if acct.type in _BANKING_TYPES:
                acct.type = "brokerage"
        else:
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


# ── Holdings CSV import ───────────────────────────────────────────────────


class HoldingsCSVImportResponse(BaseModel):
    snapshots_created: int
    snapshots_updated: int
    securities_created: int
    accounts_created: int
    prices_recorded: int
    source_format: str
    as_of: str
    errors: list[str]


@router.post("/import/holdings-csv", response_model=HoldingsCSVImportResponse)
async def import_holdings_csv(
    file: UploadFile,
    as_of: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Import holdings from a brokerage CSV (currently supports Fidelity).

    Creates or matches securities by symbol, creates or matches accounts by
    account number / name, and upserts PositionSnapshots for each holding.
    Also records current prices in PriceHistory.

    ``as_of`` is the snapshot date (YYYY-MM-DD). Defaults to today.
    """
    from datetime import date as date_type

    from finance.models.account import Account

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (10 MB limit)")
    content = raw.decode("utf-8", errors="replace")

    parsed: HoldingsCSVResult = parse_holdings_csv(content)
    if not parsed.rows and parsed.errors:
        raise HTTPException(400, detail={"errors": parsed.errors})

    # Determine snapshot date
    if as_of:
        try:
            snapshot_date = date_type.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(400, f"Invalid date format: {as_of}")
    else:
        snapshot_date = date_type.today()

    errors = list(parsed.errors)

    # 1. Resolve accounts: match by account_number, then by name, else create
    existing_accts = (await session.execute(select(Account))).scalars().all()
    acct_by_number: dict[str, Account] = {}
    acct_by_name: dict[str, Account] = {}
    for acct in existing_accts:
        if acct.account_number:
            acct_by_number[acct.account_number] = acct
        acct_by_name[acct.name] = acct

    account_map: dict[tuple[str | None, str | None], int] = {}
    accounts_created = 0

    for acct_num, acct_name in parsed.accounts_found:
        if acct_num and acct_num in acct_by_number:
            matched = acct_by_number[acct_num]
            account_map[(acct_num, acct_name)] = matched.id
            continue

        if acct_name and acct_name in acct_by_name:
            matched = acct_by_name[acct_name]
            account_map[(acct_num, acct_name)] = matched.id
            if acct_num and not matched.account_number:
                matched.account_number = acct_num
                acct_by_number[acct_num] = matched
            continue

        name = acct_name or f"Brokerage ({acct_num or 'unknown'})"
        acct = Account(
            name=name,
            type="brokerage",
            account_number=acct_num,
        )
        session.add(acct)
        await session.flush()
        account_map[(acct_num, acct_name)] = acct.id
        acct_by_name[name] = acct
        if acct_num:
            acct_by_number[acct_num] = acct
        accounts_created += 1

    # 2. Resolve securities by symbol (create if new)
    existing_secs = (await session.execute(select(Security))).scalars().all()
    sec_by_symbol: dict[str, Security] = {}
    sec_by_name: dict[str, Security] = {}
    for sec in existing_secs:
        if sec.symbol:
            sec_by_symbol[sec.symbol.upper()] = sec
        sec_by_name[sec.name] = sec

    securities_created = 0

    # 3. Upsert snapshots and prices
    snapshots_created = 0
    snapshots_updated = 0
    prices_recorded = 0

    for row in parsed.rows:
        # Resolve account
        acct_id = account_map.get((row.account_number, row.account_name))
        if acct_id is None:
            errors.append(f"Could not resolve account for {row.symbol}")
            continue

        # Resolve or create security: try symbol, then name (QIF imports key by name)
        sym_upper = row.symbol.upper()
        sec = sec_by_symbol.get(sym_upper) or sec_by_name.get(row.description)
        if sec is None:
            sec = Security(
                name=row.description,
                symbol=row.symbol,
                security_type=row.security_type,
                is_cash_equivalent=row.is_cash_equivalent,
            )
            session.add(sec)
            await session.flush()
            sec_by_symbol[sym_upper] = sec
            sec_by_name[sec.name] = sec
            securities_created += 1
        else:
            if not sec.symbol and row.symbol:
                sec.symbol = row.symbol
                sec_by_symbol[sym_upper] = sec

        # Upsert PositionSnapshot (unique on account_id + security_id + as_of)
        existing_snap = (
            await session.execute(
                select(PositionSnapshot).where(
                    PositionSnapshot.account_id == acct_id,
                    PositionSnapshot.security_id == sec.id,
                    PositionSnapshot.as_of == snapshot_date,
                )
            )
        ).scalar_one_or_none()

        if existing_snap:
            existing_snap.quantity_micros = row.quantity_micros
            existing_snap.market_value_cents = row.market_value_cents
            existing_snap.price_micros = row.price_micros if row.price_micros else None
            existing_snap.cost_basis_cents = row.cost_basis_cents
            existing_snap.source = "csv_fidelity"
            snapshots_updated += 1
        else:
            snap = PositionSnapshot(
                account_id=acct_id,
                security_id=sec.id,
                as_of=snapshot_date,
                quantity_micros=row.quantity_micros,
                market_value_cents=row.market_value_cents,
                price_micros=row.price_micros if row.price_micros else None,
                cost_basis_cents=row.cost_basis_cents,
                source="csv_fidelity",
            )
            session.add(snap)
            snapshots_created += 1

        # Record price in PriceHistory if we have one
        if row.price_micros:
            existing_price = (
                await session.execute(
                    select(PriceHistory).where(
                        PriceHistory.security_id == sec.id,
                        PriceHistory.date == snapshot_date,
                    )
                )
            ).scalar_one_or_none()
            if existing_price is None:
                session.add(PriceHistory(
                    security_id=sec.id,
                    date=snapshot_date,
                    close_micros=row.price_micros,
                    source="csv_fidelity",
                ))
                prices_recorded += 1

    await session.commit()

    return HoldingsCSVImportResponse(
        snapshots_created=snapshots_created,
        snapshots_updated=snapshots_updated,
        securities_created=securities_created,
        accounts_created=accounts_created,
        prices_recorded=prices_recorded,
        source_format=parsed.source_format,
        as_of=snapshot_date.isoformat(),
        errors=errors,
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


# ── Market data refresh ──────────────────────────────────────────────────


class BenchmarkRefreshResponse(BaseModel):
    security_id: int
    security_name: str
    symbol: str
    prices_added: int
    prices_updated: int
    prices_total: int
    set_as_benchmark: bool
    errors: list[str]


@router.post("/benchmark/refresh", response_model=BenchmarkRefreshResponse)
async def refresh_benchmark(session: AsyncSession = Depends(get_session)):
    """Download S&P 500 (SPY) monthly prices and set as portfolio benchmark."""
    result = await fetch_sp500_prices()
    if result.errors and not result.prices:
        raise HTTPException(502, detail={"errors": result.errors})

    existing = (
        await session.execute(
            select(Security).where(Security.symbol == "SPY")
        )
    ).scalars().first()

    if existing:
        security = existing
    else:
        security = Security(
            name="SPDR S&P 500 ETF Trust",
            symbol="SPY",
            security_type="etf",
        )
        session.add(security)
        await session.flush()

    existing_prices = {
        row.date: row
        for row in (
            await session.execute(
                select(PriceHistory).where(PriceHistory.security_id == security.id)
            )
        ).scalars().all()
    }

    prices_added = 0
    prices_updated = 0
    for p in result.prices:
        existing_price = existing_prices.get(p.date)
        if existing_price is None:
            session.add(PriceHistory(
                security_id=security.id,
                date=p.date,
                close_micros=p.close_micros,
                source="stooq",
            ))
            prices_added += 1
        elif existing_price.close_micros != p.close_micros:
            existing_price.close_micros = p.close_micros
            prices_updated += 1

    settings = await _get_or_create_settings(session)
    set_as_benchmark = settings.benchmark_security_id != security.id
    if set_as_benchmark:
        settings.benchmark_security_id = security.id

    await session.commit()

    return BenchmarkRefreshResponse(
        security_id=security.id,
        security_name=security.name,
        symbol="SPY",
        prices_added=prices_added,
        prices_updated=prices_updated,
        prices_total=len(result.prices),
        set_as_benchmark=set_as_benchmark,
        errors=result.errors,
    )


class RiskFreeRefreshResponse(BaseModel):
    rate_bps: int
    rate_pct: float
    source: str


@router.post("/risk-free-rate/refresh", response_model=RiskFreeRefreshResponse)
async def refresh_risk_free_rate(session: AsyncSession = Depends(get_session)):
    """Fetch the current 6-month US T-bill yield and save as risk-free rate."""
    bps, error = await fetch_risk_free_rate_bps()
    if error:
        raise HTTPException(502, error)

    settings = await _get_or_create_settings(session)
    settings.risk_free_annual_bps = bps
    await session.commit()

    return RiskFreeRefreshResponse(
        rate_bps=bps,
        rate_pct=round(bps / 100, 2),
        source="FRED DGS6MO (6-month T-bill)",
    )
