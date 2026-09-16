"""Read/Create/Update DTOs for the investment domain (ADR 0006).

Share quantities and prices cross the wire as integer millionths, matching the
columns. ``formatShares()`` / ``formatPrice()`` on the frontend do the display
conversion, as ``formatCents()`` already does for money.
"""

from datetime import date, datetime

from pydantic import BaseModel, field_validator

from finance.models.investment_settings import LOT_METHODS
from finance.models.investment_transaction import INVESTMENT_ACTIONS
from finance.models.security import SECURITY_TYPES

MICROS = 1_000_000


def _check(value: str, allowed: frozenset[str], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return value


# ── Security ────────────────────────────────────────────────────────────────


class SecurityCreate(BaseModel):
    name: str
    symbol: str | None = None
    cusip: str | None = None
    security_type: str = "other"
    is_cash_equivalent: bool = False
    benchmark_security_id: int | None = None

    @field_validator("security_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        return _check(v, SECURITY_TYPES, "security_type")


class SecurityRead(BaseModel):
    id: int
    name: str
    symbol: str | None
    cusip: str | None
    security_type: str
    is_cash_equivalent: bool
    benchmark_security_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SecurityUpdate(BaseModel):
    name: str | None = None
    symbol: str | None = None
    cusip: str | None = None
    security_type: str | None = None
    is_cash_equivalent: bool | None = None
    benchmark_security_id: int | None = None

    @field_validator("security_type")
    @classmethod
    def check_type(cls, v: str | None) -> str | None:
        return _check(v, SECURITY_TYPES, "security_type") if v is not None else v


# ── Price history ───────────────────────────────────────────────────────────


class PriceHistoryCreate(BaseModel):
    security_id: int
    date: date
    close_micros: int
    source: str = "manual"


class PriceHistoryRead(BaseModel):
    id: int
    security_id: int
    date: date
    close_micros: int
    source: str

    model_config = {"from_attributes": True}


# ── Investment transaction ──────────────────────────────────────────────────


class InvestmentTransactionCreate(BaseModel):
    account_id: int
    action: str
    trade_date: date
    security_id: int | None = None
    settle_date: date | None = None
    quantity_micros: int | None = None
    price_micros: int | None = None
    amount_cents: int = 0
    fee_cents: int = 0
    source: str = "manual"
    external_id: str | None = None
    linked_transaction_id: int | None = None
    memo: str | None = None

    @field_validator("action")
    @classmethod
    def check_action(cls, v: str) -> str:
        return _check(v, INVESTMENT_ACTIONS, "action")


class InvestmentTransactionRead(BaseModel):
    id: int
    account_id: int
    security_id: int | None
    action: str
    trade_date: date
    settle_date: date | None
    quantity_micros: int | None
    price_micros: int | None
    amount_cents: int
    fee_cents: int
    source: str
    external_id: str | None
    linked_transaction_id: int | None
    memo: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvestmentTransactionUpdate(BaseModel):
    security_id: int | None = None
    action: str | None = None
    trade_date: date | None = None
    settle_date: date | None = None
    quantity_micros: int | None = None
    price_micros: int | None = None
    amount_cents: int | None = None
    fee_cents: int | None = None
    linked_transaction_id: int | None = None
    memo: str | None = None

    @field_validator("action")
    @classmethod
    def check_action(cls, v: str | None) -> str | None:
        return _check(v, INVESTMENT_ACTIONS, "action") if v is not None else v


# ── Position snapshot ───────────────────────────────────────────────────────


class PositionSnapshotCreate(BaseModel):
    account_id: int
    security_id: int
    as_of: date
    quantity_micros: int
    market_value_cents: int
    price_micros: int | None = None
    cost_basis_cents: int | None = None
    source: str = "manual"


class PositionSnapshotRead(BaseModel):
    id: int
    account_id: int
    security_id: int
    as_of: date
    quantity_micros: int
    market_value_cents: int
    price_micros: int | None
    cost_basis_cents: int | None
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PositionSnapshotUpdate(BaseModel):
    quantity_micros: int | None = None
    market_value_cents: int | None = None
    price_micros: int | None = None
    cost_basis_cents: int | None = None


# ── Lots ────────────────────────────────────────────────────────────────────


class LotDisposalRead(BaseModel):
    id: int
    lot_id: int
    sell_txn_id: int
    quantity_micros: int
    proceeds_cents: int
    basis_cents: int
    realized_gain_cents: int
    term: str

    model_config = {"from_attributes": True}


class LotCreate(BaseModel):
    """Statement-sourced lot entry. Derived lots are written by the lot engine,
    never through this DTO, so ``source`` is fixed."""

    account_id: int
    security_id: int
    opened_at: date
    quantity_micros_original: int
    cost_basis_cents: int
    is_reinvestment: bool = False


class LotRead(BaseModel):
    id: int
    account_id: int
    security_id: int
    opened_at: date
    opened_by_txn_id: int | None
    quantity_micros_original: int
    quantity_micros_remaining: int
    cost_basis_cents: int
    is_reinvestment: bool
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Settings ────────────────────────────────────────────────────────────────


class InvestmentSettingsRead(BaseModel):
    id: int
    benchmark_security_id: int | None
    risk_free_annual_bps: int
    default_lot_method: str
    price_fetch_enabled: bool

    model_config = {"from_attributes": True}


class InvestmentSettingsUpdate(BaseModel):
    benchmark_security_id: int | None = None
    risk_free_annual_bps: int | None = None
    default_lot_method: str | None = None
    price_fetch_enabled: bool | None = None

    @field_validator("default_lot_method")
    @classmethod
    def check_method(cls, v: str | None) -> str | None:
        return _check(v, LOT_METHODS, "default_lot_method") if v is not None else v

    @field_validator("risk_free_annual_bps")
    @classmethod
    def check_rf(cls, v: int | None) -> int | None:
        if v is not None and not -10_000 <= v <= 100_000:
            raise ValueError("risk_free_annual_bps out of range")
        return v


# ── Aggregate response schemas (Phase 4) ──────────────────────────────────


class HoldingSummaryRead(BaseModel):
    security_id: int
    security_name: str
    symbol: str | None
    security_type: str
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


class AccountSummaryRead(BaseModel):
    id: int
    name: str
    type: str
    value_cents: int | None
    invested_capital_cents: int
    cost_basis_cents: int
    gain_cents: int | None
    income_cents: int
    holdings_count: int


class OverviewRead(BaseModel):
    total_value_cents: int | None
    invested_capital_cents: int
    cost_basis_cents: int
    total_gain_cents: int | None
    income_cents: int
    realized_gain_cents: int
    accounts: list[AccountSummaryRead]
    holdings_count: int


class LotDetailRead(BaseModel):
    id: int
    account_id: int
    security_id: int
    opened_at: date
    opened_by_txn_id: int | None
    quantity_micros_original: int
    quantity_micros_remaining: int
    cost_basis_cents: int
    is_reinvestment: bool
    source: str
    disposals: list[LotDisposalRead]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HoldingDetailRead(BaseModel):
    security: SecurityRead
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
    lots: list[LotDetailRead]
    transactions: list[InvestmentTransactionRead]
