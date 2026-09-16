"""FIFO lot engine — pure functions, no DB.

Replays InvestmentTransaction records for a single (account, security) and
produces Lot / LotDisposal records.  The caller supplies plain dataclass inputs
(not ORM objects) so this module stays testable without a session.

``rebuild_lots()`` is the entry point.  It expects transactions sorted by
trade_date (ties broken by id).  It returns open lots, closed disposals,
and aggregate figures that answer the "allocation vs growth" question:

- ``cost_basis_cents``: tax basis across all open lots (includes reinvested
  income — those shares *cost* something even though the money came from
  the holding itself).
- ``invested_capital_cents``: external money only — ``sum(lots where not
  is_reinvestment)``.  This is "how much of my own money went in."
- ``realized_gain_cents``: total proceeds minus total basis on closed lots.
- ``income_received_cents``: dividends + interest + capital gain
  distributions, whether reinvested or paid to cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from finance.models.investment_transaction import (
    INCOME_ACTIONS,
    LOT_CLOSING_ACTIONS,
    LOT_OPENING_ACTIONS,
)

_REINVEST_ACTIONS = frozenset({"reinvest_dividend", "reinvest_capital_gain"})


@dataclass
class TxnInput:
    id: int
    action: str
    trade_date: date
    quantity_micros: int | None = None
    price_micros: int | None = None
    amount_cents: int = 0
    fee_cents: int = 0


@dataclass
class LotRecord:
    opened_at: date
    opened_by_txn_id: int | None
    quantity_micros_original: int
    quantity_micros_remaining: int
    cost_basis_cents: int
    is_reinvestment: bool
    source: str = "derived"


@dataclass
class DisposalRecord:
    lot_index: int
    sell_txn_id: int
    quantity_micros: int
    proceeds_cents: int
    basis_cents: int
    realized_gain_cents: int
    term: str  # "short" | "long"


@dataclass
class LotResult:
    lots: list[LotRecord] = field(default_factory=list)
    disposals: list[DisposalRecord] = field(default_factory=list)
    cost_basis_cents: int = 0
    invested_capital_cents: int = 0
    realized_gain_cents: int = 0
    income_received_cents: int = 0


def rebuild_lots(txns: list[TxnInput]) -> LotResult:
    """Replay a trade-date-sorted transaction list and return FIFO lots.

    Transactions must be for a single (account, security) pair, sorted by
    trade_date then id.
    """
    lots: list[LotRecord] = []
    disposals: list[DisposalRecord] = []
    income_received_cents = 0
    realized_gain_cents = 0

    for txn in txns:
        if txn.action in INCOME_ACTIONS:
            income_received_cents += abs(txn.amount_cents)

        if txn.action in LOT_OPENING_ACTIONS:
            _open_lot(lots, txn)
        elif txn.action in LOT_CLOSING_ACTIONS:
            _close_lots_fifo(lots, disposals, txn)
        elif txn.action == "split":
            _apply_split(lots, txn)
        elif txn.action == "return_of_capital":
            _apply_return_of_capital(lots, txn)

    for d in disposals:
        realized_gain_cents += d.realized_gain_cents

    cost_basis_cents = sum(
        lot.cost_basis_cents
        for lot in lots
        if lot.quantity_micros_remaining > 0
    )
    invested_capital_cents = sum(
        lot.cost_basis_cents
        for lot in lots
        if lot.quantity_micros_remaining > 0 and not lot.is_reinvestment
    )

    return LotResult(
        lots=lots,
        disposals=disposals,
        cost_basis_cents=cost_basis_cents,
        invested_capital_cents=invested_capital_cents,
        realized_gain_cents=realized_gain_cents,
        income_received_cents=income_received_cents,
    )


def _open_lot(lots: list[LotRecord], txn: TxnInput) -> None:
    qty = txn.quantity_micros or 0
    if qty <= 0:
        return
    basis = abs(txn.amount_cents) + txn.fee_cents
    lots.append(
        LotRecord(
            opened_at=txn.trade_date,
            opened_by_txn_id=txn.id,
            quantity_micros_original=qty,
            quantity_micros_remaining=qty,
            cost_basis_cents=basis,
            is_reinvestment=txn.action in _REINVEST_ACTIONS,
        )
    )


def _close_lots_fifo(
    lots: list[LotRecord],
    disposals: list[DisposalRecord],
    txn: TxnInput,
) -> None:
    remaining = abs(txn.quantity_micros or 0)
    if remaining <= 0:
        return
    proceeds_total = abs(txn.amount_cents) - txn.fee_cents

    proceeds_allocated_so_far = 0
    qty_allocated_so_far = 0
    total_sell_qty = abs(txn.quantity_micros or 1)

    for i, lot in enumerate(lots):
        if remaining <= 0:
            break
        if lot.quantity_micros_remaining <= 0:
            continue

        take = min(remaining, lot.quantity_micros_remaining)
        fraction = take / lot.quantity_micros_remaining
        basis_allocated = round(lot.cost_basis_cents * fraction)

        qty_allocated_so_far += take
        if remaining - take <= 0:
            proceeds_allocated = proceeds_total - proceeds_allocated_so_far
        else:
            proceeds_allocated = round(proceeds_total * (qty_allocated_so_far / total_sell_qty)) - proceeds_allocated_so_far
        proceeds_allocated_so_far += proceeds_allocated

        gain = proceeds_allocated - basis_allocated

        held_days = (txn.trade_date - lot.opened_at).days
        term = "long" if held_days > 365 else "short"

        disposals.append(
            DisposalRecord(
                lot_index=i,
                sell_txn_id=txn.id,
                quantity_micros=take,
                proceeds_cents=proceeds_allocated,
                basis_cents=basis_allocated,
                realized_gain_cents=gain,
                term=term,
            )
        )

        lot.quantity_micros_remaining -= take
        lot.cost_basis_cents -= basis_allocated
        remaining -= take


def _apply_split(lots: list[LotRecord], txn: TxnInput) -> None:
    """Stock split: multiply share counts, basis stays the same.

    The transaction's quantity_micros holds the post-split total; we compute
    the ratio from pre-split total across open lots.
    """
    pre_split_total = sum(
        lot.quantity_micros_remaining for lot in lots if lot.quantity_micros_remaining > 0
    )
    if pre_split_total <= 0:
        return
    post_split_total = txn.quantity_micros or 0
    if post_split_total <= 0:
        return
    ratio = post_split_total / pre_split_total
    for lot in lots:
        if lot.quantity_micros_remaining > 0:
            lot.quantity_micros_original = round(lot.quantity_micros_original * ratio)
            lot.quantity_micros_remaining = round(lot.quantity_micros_remaining * ratio)


def _apply_return_of_capital(lots: list[LotRecord], txn: TxnInput) -> None:
    """Return of capital reduces cost basis pro-rata across open lots."""
    total_basis = sum(
        lot.cost_basis_cents for lot in lots if lot.quantity_micros_remaining > 0
    )
    if total_basis <= 0:
        return
    roc_amount = abs(txn.amount_cents)
    for lot in lots:
        if lot.quantity_micros_remaining > 0 and lot.cost_basis_cents > 0:
            fraction = lot.cost_basis_cents / total_basis
            reduction = min(round(roc_amount * fraction), lot.cost_basis_cents)
            lot.cost_basis_cents -= reduction
