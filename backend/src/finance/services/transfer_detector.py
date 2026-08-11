"""Detect account-to-account transfers in transaction history.

A transfer shows up as two transactions: a debit in one account and a
matching credit in another, within a small time window.  This module
finds those pairs deterministically — no LLM needed.

Matching criteria:
  - Different account_id
  - Same absolute amount (one positive, one negative)
  - posted_at within ±3 days
  - Neither already paired to a different transfer

The ``transfer_pair_id`` column links the two sides.  By convention
the pair ID equals the smaller transaction ID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.transaction import Transaction

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 3


@dataclass
class TransferPair:
    pair_id: int
    debit_txn_id: int
    credit_txn_id: int
    debit_account_id: int
    credit_account_id: int
    amount_cents: int
    debit_description: str | None
    credit_description: str | None
    debit_posted_at: str
    credit_posted_at: str


@dataclass
class DetectionResult:
    new_pairs: int
    cleared_pairs: int
    total_pairs: int


async def detect_transfers(
    session: AsyncSession,
    *,
    account_ids: list[int] | None = None,
    window_days: int = _WINDOW_DAYS,
    dry_run: bool = False,
) -> DetectionResult:
    """Scan transactions for transfer pairs and write ``transfer_pair_id``.

    Only considers transactions not already paired.  Returns how many
    new pairs were found.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.transfer_pair_id.is_(None))
        .order_by(Transaction.posted_at)
    )
    if account_ids:
        stmt = stmt.where(Transaction.account_id.in_(account_ids))

    rows = list((await session.execute(stmt)).scalars().all())

    positives = [t for t in rows if t.amount_cents > 0]
    negatives = [t for t in rows if t.amount_cents < 0]

    paired_ids: set[int] = set()
    new_pairs = 0

    for neg in negatives:
        if neg.id in paired_ids:
            continue
        abs_amount = abs(neg.amount_cents)

        for pos in positives:
            if pos.id in paired_ids:
                continue
            if pos.account_id == neg.account_id:
                continue
            if pos.amount_cents != abs_amount:
                continue

            day_diff = abs((pos.posted_at - neg.posted_at).days)
            if day_diff > window_days:
                continue

            pair_id = min(neg.id, pos.id)

            if not dry_run:
                neg.transfer_pair_id = pair_id
                pos.transfer_pair_id = pair_id

            paired_ids.add(neg.id)
            paired_ids.add(pos.id)
            new_pairs += 1
            logger.debug(
                "Transfer pair %d: txn %d (%d cents) <-> txn %d (%d cents)",
                pair_id,
                neg.id,
                neg.amount_cents,
                pos.id,
                pos.amount_cents,
            )
            break

    if not dry_run and new_pairs > 0:
        await session.commit()

    total_q = select(func.count(func.distinct(Transaction.transfer_pair_id))).where(
        Transaction.transfer_pair_id.isnot(None)
    )
    total_pairs = (await session.execute(total_q)).scalar() or 0

    return DetectionResult(
        new_pairs=new_pairs,
        cleared_pairs=0,
        total_pairs=total_pairs,
    )


async def clear_transfer_pair(
    session: AsyncSession, pair_id: int
) -> int:
    """Remove a transfer pairing (user says it's not a transfer)."""
    stmt = select(Transaction).where(Transaction.transfer_pair_id == pair_id)
    txns = list((await session.execute(stmt)).scalars().all())
    for t in txns:
        t.transfer_pair_id = None
    await session.commit()
    return len(txns)


async def list_transfer_pairs(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[TransferPair], int]:
    """List all detected transfer pairs."""
    sub = (
        select(Transaction.transfer_pair_id)
        .where(Transaction.transfer_pair_id.isnot(None))
        .group_by(Transaction.transfer_pair_id)
    )
    count_q = select(func.count()).select_from(sub.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    pair_ids_q = (
        select(Transaction.transfer_pair_id)
        .where(Transaction.transfer_pair_id.isnot(None))
        .group_by(Transaction.transfer_pair_id)
        .order_by(Transaction.transfer_pair_id.desc())
        .offset(offset)
        .limit(limit)
    )
    pair_ids = [
        row[0] for row in (await session.execute(pair_ids_q)).all()
    ]

    if not pair_ids:
        return [], total

    txn_q = (
        select(Transaction)
        .where(Transaction.transfer_pair_id.in_(pair_ids))
        .order_by(Transaction.transfer_pair_id, Transaction.amount_cents)
    )
    txns = list((await session.execute(txn_q)).scalars().all())

    by_pair: dict[int, list[Transaction]] = {}
    for t in txns:
        by_pair.setdefault(t.transfer_pair_id, []).append(t)

    pairs: list[TransferPair] = []
    for pid in pair_ids:
        group = by_pair.get(pid, [])
        if len(group) < 2:
            continue

        debit = next((t for t in group if t.amount_cents < 0), group[0])
        credit = next((t for t in group if t.amount_cents > 0), group[1])

        pairs.append(
            TransferPair(
                pair_id=pid,
                debit_txn_id=debit.id,
                credit_txn_id=credit.id,
                debit_account_id=debit.account_id,
                credit_account_id=credit.account_id,
                amount_cents=abs(debit.amount_cents),
                debit_description=debit.description,
                credit_description=credit.description,
                debit_posted_at=debit.posted_at.isoformat(),
                credit_posted_at=credit.posted_at.isoformat(),
            )
        )

    return pairs, total
