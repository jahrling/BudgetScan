"""Aggregate queries for the investment domain.

Composes data from lots, prices, transactions, and snapshots into the
summary shapes the frontend views consume.  Pure async queries — the
financial math lives in investment_math.py and lot_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from finance.models.account import Account
from finance.models.investment_transaction import INCOME_ACTIONS, InvestmentTransaction
from finance.models.lot import Lot, LotDisposal
from finance.models.security import PriceHistory, Security

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
                func.case(
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
    if not lot_rows:
        return []

    prices = await _latest_prices(session)
    income_map = await _income_by_holding(session, account_id)
    realized_map = await _realized_gains_by_holding(session, account_id)

    sec_ids = {r[1] for r in lot_rows}
    acct_ids = {r[0] for r in lot_rows}
    secs = {
        s.id: s
        for s in (
            await session.execute(select(Security).where(Security.id.in_(sec_ids)))
        ).scalars().all()
    }
    accts = {
        a.id: a
        for a in (
            await session.execute(select(Account).where(Account.id.in_(acct_ids)))
        ).scalars().all()
    }

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
    price_micros = price_info[0] if price_info else None
    price_date = price_info[1] if price_info else None
    mv = _market_value_cents(qty, price_micros) if price_micros is not None and qty > 0 else None
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
