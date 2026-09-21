"""Aggregate queries for the investment domain.

Composes data from lots, prices, transactions, and snapshots into the
summary shapes the frontend views consume.  Pure async queries — the
financial math lives in investment_math.py and lot_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from finance.models.account import Account
from finance.models.investment_settings import InvestmentSettings
from finance.models.investment_transaction import INCOME_ACTIONS, InvestmentTransaction
from finance.models.lot import Lot, LotDisposal
from finance.models.position_snapshot import PositionSnapshot
from finance.models.security import PriceHistory, Security
from finance.services.investment_math import (
    CashFlow,
    RiskMetrics,
    compute_risk_metrics,
    decompose_return,
    monthly_return_series,
    xirr,
)

MICROS = 1_000_000


def _market_value_cents(quantity_micros: int, price_micros: int) -> int:
    """quantity (micros) x price (micros) → cents."""
    return int(quantity_micros * price_micros // (MICROS * MICROS // 100))


# ── Data containers ───────────────────────────────────────────────────────


@dataclass
class HoldingRow:
    security_id: int
    security_name: str
    symbol: str | None
    security_type: str
    is_cash_equivalent: bool
    account_id: int
    account_name: str
    account_type: str
    quantity_micros: int
    latest_price_micros: int | None
    latest_price_date: date | None
    market_value_cents: int | None
    cost_basis_cents: int
    invested_capital_cents: int
    unrealized_gain_cents: int | None
    income_cents: int
    realized_gain_cents: int


@dataclass
class AccountRow:
    id: int
    name: str
    type: str
    value_cents: int | None
    invested_capital_cents: int
    cost_basis_cents: int
    gain_cents: int | None
    income_cents: int
    holdings_count: int


@dataclass
class OverviewData:
    total_value_cents: int | None
    invested_capital_cents: int
    cost_basis_cents: int
    total_gain_cents: int | None
    income_cents: int
    realized_gain_cents: int
    accounts: list[AccountRow]
    holdings_count: int


@dataclass
class LotWithDisposals:
    lot: Lot
    disposals: list[LotDisposal] = field(default_factory=list)


@dataclass
class HoldingDetail:
    security: Security
    account_id: int | None
    account_name: str | None
    quantity_micros: int
    latest_price_micros: int | None
    latest_price_date: date | None
    market_value_cents: int | None
    cost_basis_cents: int
    invested_capital_cents: int
    unrealized_gain_cents: int | None
    income_cents: int
    realized_gain_cents: int
    lots: list[LotWithDisposals]
    transactions: list[InvestmentTransaction]


# ── Latest price lookup ───────────────────────────────────────────────────


async def _latest_prices(
    session: AsyncSession, security_id: int | None = None
) -> dict[int, tuple[int, date]]:
    """Map security_id → (close_micros, date) for the most recent price row."""
    base = select(
        PriceHistory.security_id,
        func.max(PriceHistory.date).label("max_date"),
    )
    if security_id is not None:
        base = base.where(PriceHistory.security_id == security_id)
    subq = base.group_by(PriceHistory.security_id).subquery()
    rows = await session.execute(
        select(PriceHistory).join(
            subq,
            (PriceHistory.security_id == subq.c.security_id)
            & (PriceHistory.date == subq.c.max_date),
        )
    )
    return {
        ph.security_id: (ph.close_micros, ph.date)
        for ph in rows.scalars().all()
    }


# ── Income per (account, security) ───────────────────────────────────────


async def _income_by_holding(
    session: AsyncSession, account_id: int | None = None
) -> dict[tuple[int, int | None], int]:
    """Sum |amount_cents| for income actions, keyed by (account_id, security_id)."""
    q = (
        select(
            InvestmentTransaction.account_id,
            InvestmentTransaction.security_id,
            func.sum(func.abs(InvestmentTransaction.amount_cents)).label("income"),
        )
        .where(InvestmentTransaction.action.in_(INCOME_ACTIONS))
        .group_by(InvestmentTransaction.account_id, InvestmentTransaction.security_id)
    )
    if account_id is not None:
        q = q.where(InvestmentTransaction.account_id == account_id)
    rows = await session.execute(q)
    return {(r[0], r[1]): int(r[2]) for r in rows.all()}


# ── Realized gains per (account, security) ────────────────────────────────


async def _realized_gains_by_holding(
    session: AsyncSession, account_id: int | None = None
) -> dict[tuple[int, int], int]:
    q = (
        select(
            Lot.account_id,
            Lot.security_id,
            func.sum(LotDisposal.realized_gain_cents).label("gain"),
        )
        .join(LotDisposal, LotDisposal.lot_id == Lot.id)
        .group_by(Lot.account_id, Lot.security_id)
    )
    if account_id is not None:
        q = q.where(Lot.account_id == account_id)
    rows = await session.execute(q)
    return {(r[0], r[1]): int(r[2]) for r in rows.all()}


# ── Holdings ──────────────────────────────────────────────────────────────


async def get_holdings(
    session: AsyncSession, account_id: int | None = None
) -> list[HoldingRow]:
    """Per-(account, security) holding summaries from lots + latest prices."""

    lot_q = (
        select(
            Lot.account_id,
            Lot.security_id,
            func.sum(Lot.quantity_micros_remaining).label("qty"),
            func.sum(Lot.cost_basis_cents).label("basis"),
            func.sum(
                case(
                    (Lot.is_reinvestment.is_(False), Lot.cost_basis_cents),
                    else_=0,
                )
            ).label("invested"),
        )
        .where(Lot.quantity_micros_remaining > 0)
        .group_by(Lot.account_id, Lot.security_id)
    )
    if account_id is not None:
        lot_q = lot_q.where(Lot.account_id == account_id)

    lot_rows = (await session.execute(lot_q)).all()

    prices = await _latest_prices(session)
    income_map = await _income_by_holding(session, account_id)
    realized_map = await _realized_gains_by_holding(session, account_id)

    lot_pairs: set[tuple[int, int]] = set()
    sec_ids: set[int] = set()
    acct_ids: set[int] = set()

    for r in lot_rows:
        lot_pairs.add((r[0], r[1]))
        sec_ids.add(r[1])
        acct_ids.add(r[0])

    # Also include the latest PositionSnapshot per (account, security)
    # for pairs that have no open lots — this is how statement-OCR data
    # reaches the Holdings view.
    snap_subq = (
        select(
            PositionSnapshot.account_id,
            PositionSnapshot.security_id,
            func.max(PositionSnapshot.as_of).label("max_date"),
        )
        .group_by(PositionSnapshot.account_id, PositionSnapshot.security_id)
    )
    if account_id is not None:
        snap_subq = snap_subq.where(PositionSnapshot.account_id == account_id)
    snap_subq = snap_subq.subquery()

    snap_rows = (
        await session.execute(
            select(PositionSnapshot).join(
                snap_subq,
                (PositionSnapshot.account_id == snap_subq.c.account_id)
                & (PositionSnapshot.security_id == snap_subq.c.security_id)
                & (PositionSnapshot.as_of == snap_subq.c.max_date),
            )
        )
    ).scalars().all()

    for snap in snap_rows:
        sec_ids.add(snap.security_id)
        acct_ids.add(snap.account_id)

    if not lot_rows and not snap_rows:
        return []

    secs = {
        s.id: s
        for s in (
            await session.execute(select(Security).where(Security.id.in_(sec_ids)))
        ).scalars().all()
    } if sec_ids else {}
    accts = {
        a.id: a
        for a in (
            await session.execute(select(Account).where(Account.id.in_(acct_ids)))
        ).scalars().all()
    } if acct_ids else {}

    holdings: list[HoldingRow] = []
    for acct_id, sec_id, qty, basis, invested in lot_rows:
        sec = secs.get(sec_id)
        acct = accts.get(acct_id)
        if sec is None or acct is None:
            continue
        if sec.is_cash_equivalent:
            continue

        qty = int(qty)
        basis = int(basis)
        invested = int(invested)
        price_info = prices.get(sec_id)
        price_micros = price_info[0] if price_info else None
        price_date = price_info[1] if price_info else None
        mv = _market_value_cents(qty, price_micros) if price_micros is not None else None
        unrealized = (mv - basis) if mv is not None else None
        income = income_map.get((acct_id, sec_id), 0)
        realized = realized_map.get((acct_id, sec_id), 0)

        holdings.append(HoldingRow(
            security_id=sec_id,
            security_name=sec.name,
            symbol=sec.symbol,
            security_type=sec.security_type,
            is_cash_equivalent=sec.is_cash_equivalent,
            account_id=acct_id,
            account_name=acct.name,
            account_type=acct.type,
            quantity_micros=qty,
            latest_price_micros=price_micros,
            latest_price_date=price_date,
            market_value_cents=mv,
            cost_basis_cents=basis,
            invested_capital_cents=invested,
            unrealized_gain_cents=unrealized,
            income_cents=income,
            realized_gain_cents=realized,
        ))

    # Add snapshot-only holdings (no open lots for this pair)
    for snap in snap_rows:
        if (snap.account_id, snap.security_id) in lot_pairs:
            continue
        sec = secs.get(snap.security_id)
        acct = accts.get(snap.account_id)
        if sec is None or acct is None:
            continue
        if sec.is_cash_equivalent:
            continue

        price_info = prices.get(snap.security_id)
        price_micros = snap.price_micros or (price_info[0] if price_info else None)
        price_date = price_info[1] if price_info else snap.as_of if snap.price_micros else None
        mv = snap.market_value_cents
        basis = snap.cost_basis_cents or 0
        unrealized = (mv - basis) if mv is not None else None
        income = income_map.get((snap.account_id, snap.security_id), 0)
        realized = realized_map.get((snap.account_id, snap.security_id), 0)

        holdings.append(HoldingRow(
            security_id=snap.security_id,
            security_name=sec.name,
            symbol=sec.symbol,
            security_type=sec.security_type,
            is_cash_equivalent=sec.is_cash_equivalent,
            account_id=snap.account_id,
            account_name=acct.name,
            account_type=acct.type,
            quantity_micros=snap.quantity_micros,
            latest_price_micros=price_micros,
            latest_price_date=price_date,
            market_value_cents=mv,
            cost_basis_cents=basis,
            invested_capital_cents=0,
            unrealized_gain_cents=unrealized,
            income_cents=income,
            realized_gain_cents=realized,
        ))

    holdings.sort(key=lambda h: (h.account_name, h.security_name))
    return holdings


# ── Overview ──────────────────────────────────────────────────────────────


async def get_overview(session: AsyncSession) -> OverviewData:
    """Portfolio-level summary aggregated from holdings."""
    holdings = await get_holdings(session)

    accts: dict[int, AccountRow] = {}
    total_value: int | None = 0
    total_invested = 0
    total_basis = 0
    total_income = 0
    total_realized = 0
    has_any_value = False

    for h in holdings:
        if h.account_id not in accts:
            accts[h.account_id] = AccountRow(
                id=h.account_id,
                name=h.account_name,
                type=h.account_type,
                value_cents=0,
                invested_capital_cents=0,
                cost_basis_cents=0,
                gain_cents=0,
                income_cents=0,
                holdings_count=0,
            )
        ar = accts[h.account_id]
        ar.holdings_count += 1
        ar.invested_capital_cents += h.invested_capital_cents
        ar.cost_basis_cents += h.cost_basis_cents
        ar.income_cents += h.income_cents
        total_invested += h.invested_capital_cents
        total_basis += h.cost_basis_cents
        total_income += h.income_cents
        total_realized += h.realized_gain_cents

        if h.market_value_cents is not None:
            has_any_value = True
            if ar.value_cents is not None:
                ar.value_cents += h.market_value_cents
            if total_value is not None:
                total_value += h.market_value_cents
        else:
            ar.value_cents = None
            total_value = None

    for ar in accts.values():
        if ar.value_cents is not None:
            ar.gain_cents = ar.value_cents - ar.cost_basis_cents
        else:
            ar.gain_cents = None

    if not has_any_value:
        total_value = None
    total_gain = (total_value - total_basis) if total_value is not None else None

    return OverviewData(
        total_value_cents=total_value,
        invested_capital_cents=total_invested,
        cost_basis_cents=total_basis,
        total_gain_cents=total_gain,
        income_cents=total_income,
        realized_gain_cents=total_realized,
        accounts=sorted(accts.values(), key=lambda a: a.name),
        holdings_count=len(holdings),
    )


# ── Holding detail ────────────────────────────────────────────────────────


async def get_holding_detail(
    session: AsyncSession,
    security_id: int,
    account_id: int | None = None,
) -> HoldingDetail | None:
    """Full detail for one security across accounts (or filtered to one)."""
    security = await session.get(Security, security_id)
    if security is None:
        return None

    lot_q = (
        select(Lot)
        .where(Lot.security_id == security_id)
        .options(selectinload(Lot.disposals))
        .order_by(Lot.opened_at)
    )
    if account_id is not None:
        lot_q = lot_q.where(Lot.account_id == account_id)
    lots_result = await session.execute(lot_q)
    lots = list(lots_result.scalars().unique().all())

    txn_q = (
        select(InvestmentTransaction)
        .where(InvestmentTransaction.security_id == security_id)
        .order_by(InvestmentTransaction.trade_date.desc())
    )
    if account_id is not None:
        txn_q = txn_q.where(InvestmentTransaction.account_id == account_id)
    txns_result = await session.execute(txn_q)
    txns = list(txns_result.scalars().all())

    qty = sum(lt.quantity_micros_remaining for lt in lots if lt.quantity_micros_remaining > 0)
    basis = sum(lt.cost_basis_cents for lt in lots if lt.quantity_micros_remaining > 0)
    invested = sum(
        lt.cost_basis_cents
        for lt in lots
        if lt.quantity_micros_remaining > 0 and not lt.is_reinvestment
    )
    income = sum(abs(t.amount_cents) for t in txns if t.action in INCOME_ACTIONS)
    realized = sum(
        d.realized_gain_cents
        for lt in lots
        for d in (lt.disposals or [])
    )

    prices = await _latest_prices(session, security_id=security_id)
    price_info = prices.get(security_id)

    # Fall back to latest PositionSnapshot when no lots exist
    if qty == 0:
        snap_q = (
            select(PositionSnapshot)
            .where(PositionSnapshot.security_id == security_id)
            .order_by(PositionSnapshot.as_of.desc())
            .limit(1)
        )
        if account_id is not None:
            snap_q = snap_q.where(PositionSnapshot.account_id == account_id)
        snap = (await session.execute(snap_q)).scalar_one_or_none()
        if snap is not None:
            qty = snap.quantity_micros
            mv = snap.market_value_cents
            basis = snap.cost_basis_cents or 0
            price_micros = snap.price_micros or (price_info[0] if price_info else None)
            price_date = price_info[1] if price_info else snap.as_of if snap.price_micros else None
            unrealized = (mv - basis) if mv is not None else None
        else:
            price_micros = price_info[0] if price_info else None
            price_date = price_info[1] if price_info else None
            mv = None
            unrealized = None
    else:
        price_micros = price_info[0] if price_info else None
        price_date = price_info[1] if price_info else None
        mv = _market_value_cents(qty, price_micros) if price_micros is not None else None
        unrealized = (mv - basis) if mv is not None else None

    acct_name: str | None = None
    if account_id is not None:
        acct = await session.get(Account, account_id)
        acct_name = acct.name if acct else None

    lot_details = [
        LotWithDisposals(lot=lt, disposals=list(lt.disposals or []))
        for lt in lots
    ]

    return HoldingDetail(
        security=security,
        account_id=account_id,
        account_name=acct_name,
        quantity_micros=qty,
        latest_price_micros=price_micros,
        latest_price_date=price_date,
        market_value_cents=mv,
        cost_basis_cents=basis,
        invested_capital_cents=invested,
        unrealized_gain_cents=unrealized,
        income_cents=income,
        realized_gain_cents=realized,
        lots=lot_details,
        transactions=txns,
    )


# ── Performance analytics ────────────────────────────────────────────────


@dataclass
class MonthlyReturn:
    date: str
    portfolio: float
    benchmark: float | None


@dataclass
class ReturnDecomposition:
    contributions_cents: int
    income_cents: int
    appreciation_cents: int


@dataclass
class PerformanceData:
    risk_metrics: RiskMetrics | None
    portfolio_return: float | None
    benchmark_return: float | None
    xirr_return: float | None
    decomposition: ReturnDecomposition | None
    monthly_returns: list[MonthlyReturn]
    benchmark_name: str | None
    benchmark_symbol: str | None
    has_benchmark: bool
    error: str | None = None


async def get_performance(
    session: AsyncSession,
    account_id: int | None = None,
) -> PerformanceData:
    """Compute portfolio performance and risk metrics vs benchmark.

    Aggregates all PositionSnapshots into a monthly portfolio value series,
    gathers cash flows from InvestmentTransactions, computes Modified Dietz
    monthly returns, then compares against the benchmark's PriceHistory.
    """
    # Load settings for benchmark and risk-free rate
    settings = (
        await session.execute(select(InvestmentSettings).where(InvestmentSettings.id == 1))
    ).scalar_one_or_none()

    benchmark_sec: Security | None = None
    if settings and settings.benchmark_security_id:
        benchmark_sec = await session.get(Security, settings.benchmark_security_id)

    risk_free_annual = (settings.risk_free_annual_bps / 10_000) if settings else 0.0

    # 1. Get portfolio monthly valuations from snapshots
    #    Aggregate all snapshots by as_of date → total market value
    snap_q = (
        select(
            PositionSnapshot.as_of,
            func.sum(PositionSnapshot.market_value_cents).label("total_value"),
        )
        .group_by(PositionSnapshot.as_of)
        .order_by(PositionSnapshot.as_of)
    )
    if account_id is not None:
        snap_q = snap_q.where(PositionSnapshot.account_id == account_id)
    snap_rows = (await session.execute(snap_q)).all()

    if len(snap_rows) < 2:
        return PerformanceData(
            risk_metrics=None,
            portfolio_return=None,
            benchmark_return=None,
            xirr_return=None,
            decomposition=None,
            monthly_returns=[],
            benchmark_name=benchmark_sec.name if benchmark_sec else None,
            benchmark_symbol=benchmark_sec.symbol if benchmark_sec else None,
            has_benchmark=benchmark_sec is not None,
            error="Need at least 2 position snapshots to compute returns",
        )

    snapshots: list[tuple[date, int]] = [
        (row[0], int(row[1])) for row in snap_rows
    ]

    # 2. Get cash flows (contributions/withdrawals) from investment transactions
    flow_actions = {"cash_in", "cash_out", "shares_in", "shares_out"}
    flow_q = (
        select(InvestmentTransaction)
        .where(InvestmentTransaction.action.in_(flow_actions))
        .order_by(InvestmentTransaction.trade_date)
    )
    if account_id is not None:
        flow_q = flow_q.where(InvestmentTransaction.account_id == account_id)
    flow_rows = (await session.execute(flow_q)).scalars().all()

    cash_flows = [
        CashFlow(date=t.trade_date, amount_cents=t.amount_cents)
        for t in flow_rows
    ]

    # 3. Compute portfolio monthly return series
    port_series = monthly_return_series(snapshots, cash_flows)

    if not port_series:
        return PerformanceData(
            risk_metrics=None,
            portfolio_return=None,
            benchmark_return=None,
            xirr_return=None,
            decomposition=None,
            monthly_returns=[],
            benchmark_name=benchmark_sec.name if benchmark_sec else None,
            benchmark_symbol=benchmark_sec.symbol if benchmark_sec else None,
            has_benchmark=benchmark_sec is not None,
            error="Could not compute monthly returns from snapshots",
        )

    # Cumulative portfolio return
    port_cumulative = 1.0
    for _, r in port_series:
        port_cumulative *= (1.0 + r)
    portfolio_return = port_cumulative - 1.0

    # 4. Get benchmark monthly returns from PriceHistory
    bench_series: list[float] = []
    benchmark_return: float | None = None
    monthly_returns: list[MonthlyReturn] = []

    if benchmark_sec:
        price_q = (
            select(PriceHistory)
            .where(PriceHistory.security_id == benchmark_sec.id)
            .order_by(PriceHistory.date)
        )
        bench_prices = (await session.execute(price_q)).scalars().all()

        if len(bench_prices) >= 2:
            bench_by_date: dict[date, int] = {
                p.date: p.close_micros for p in bench_prices
            }

            for month_date, port_r in port_series:
                # Find the closest benchmark price on or before this date
                best_date = None
                for bd in sorted(bench_by_date.keys()):
                    if bd <= month_date:
                        best_date = bd
                if best_date is not None:
                    bench_series.append(best_date)

            # Compute benchmark returns for matching months
            bench_returns: list[float] = []
            if len(bench_series) >= 2:
                for i in range(1, len(bench_series)):
                    prev_price = bench_by_date[bench_series[i - 1]]
                    curr_price = bench_by_date[bench_series[i]]
                    if prev_price > 0:
                        bench_returns.append((curr_price - prev_price) / prev_price)
                    else:
                        bench_returns.append(0.0)

            # Align: port_series has N entries, bench_returns has N-1
            # We need to trim port_series to match
            port_returns_aligned = [r for _, r in port_series]
            if len(bench_returns) < len(port_returns_aligned):
                port_returns_aligned = port_returns_aligned[-len(bench_returns):]
                port_dates = [d for d, _ in port_series][-len(bench_returns):]
            else:
                bench_returns = bench_returns[-len(port_returns_aligned):]
                port_dates = [d for d, _ in port_series]

            # Build monthly returns for chart
            for i, d in enumerate(port_dates):
                br = bench_returns[i] if i < len(bench_returns) else None
                monthly_returns.append(MonthlyReturn(
                    date=d.isoformat(),
                    portfolio=port_returns_aligned[i],
                    benchmark=br,
                ))

            # Cumulative benchmark return
            if bench_returns:
                bench_cumulative = 1.0
                for r in bench_returns:
                    bench_cumulative *= (1.0 + r)
                benchmark_return = bench_cumulative - 1.0

            # 5. Compute risk metrics
            risk_metrics = compute_risk_metrics(
                port_returns_aligned, bench_returns, risk_free_annual,
            )
        else:
            risk_metrics = None
            for d, r in port_series:
                monthly_returns.append(MonthlyReturn(
                    date=d.isoformat(), portfolio=r, benchmark=None,
                ))
    else:
        risk_metrics = None
        for d, r in port_series:
            monthly_returns.append(MonthlyReturn(
                date=d.isoformat(), portfolio=r, benchmark=None,
            ))

    # 6. XIRR — money-weighted return
    #    Build NPV cash flows: each contribution is negative (money in),
    #    and the final portfolio value is positive (money out).
    xirr_flows: list[CashFlow] = []
    first_date, first_val = snapshots[0]
    last_date, last_val = snapshots[-1]
    xirr_flows.append(CashFlow(date=first_date, amount_cents=-first_val))
    for cf in cash_flows:
        if first_date < cf.date <= last_date:
            xirr_flows.append(CashFlow(date=cf.date, amount_cents=-cf.amount_cents))
    xirr_flows.append(CashFlow(date=last_date, amount_cents=last_val))
    xirr_return = xirr(xirr_flows) if len(xirr_flows) >= 2 else None

    # 7. Return decomposition
    net_contributions = sum(cf.amount_cents for cf in cash_flows if first_date < cf.date <= last_date)
    income_q = (
        select(func.sum(func.abs(InvestmentTransaction.amount_cents)))
        .where(InvestmentTransaction.action.in_(INCOME_ACTIONS))
    )
    if account_id is not None:
        income_q = income_q.where(InvestmentTransaction.account_id == account_id)
    total_income = (await session.execute(income_q)).scalar() or 0
    decomp_result = decompose_return(first_val, last_val, net_contributions, int(total_income))
    decomposition = ReturnDecomposition(
        contributions_cents=decomp_result.net_contributions_cents,
        income_cents=decomp_result.income_cents,
        appreciation_cents=decomp_result.price_appreciation_cents,
    )

    return PerformanceData(
        risk_metrics=risk_metrics,
        portfolio_return=portfolio_return,
        benchmark_return=benchmark_return,
        xirr_return=xirr_return,
        decomposition=decomposition,
        monthly_returns=monthly_returns,
        benchmark_name=benchmark_sec.name if benchmark_sec else None,
        benchmark_symbol=benchmark_sec.symbol if benchmark_sec else None,
        has_benchmark=benchmark_sec is not None,
    )
