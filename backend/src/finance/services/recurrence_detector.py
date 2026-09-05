"""Detect recurring transactions by payee, amount, and cadence patterns.

Groups transactions by normalized payee and amount bucket (10% tolerance),
then checks interval regularity to assign a cadence label. Results are
stored as ``is_recurring``, ``recurrence_cadence``, and ``recurrence_group_id``
on the Transaction model.

Idempotent — each run clears previous flags and recomputes from scratch.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.transaction import Transaction
from finance.services.merchant_resolver import clean_description, normalize_for_matching

logger = logging.getLogger(__name__)

_AMOUNT_TOLERANCE = 0.10  # 10%
_MIN_GROUP_MONTHLY = 3
_MIN_GROUP_WEEKLY = 4
_MIN_GROUP_ANNUAL = 2

_CADENCE_SPECS: list[tuple[str, float, float, float, int]] = [
    # (cadence, min_median_days, max_median_days, max_cv, min_count)
    ("weekly", 5, 9, 0.35, _MIN_GROUP_WEEKLY),
    ("biweekly", 12, 16, 0.30, _MIN_GROUP_WEEKLY),
    ("monthly", 25, 35, 0.30, _MIN_GROUP_MONTHLY),
    ("annual", 350, 380, 0.15, _MIN_GROUP_ANNUAL),
]


@dataclass
class RecurrenceGroup:
    transaction_ids: list[int]
    cadence: str
    group_id: int


@dataclass
class DetectionResult:
    groups_found: int = 0
    transactions_flagged: int = 0
    transactions_cleared: int = 0
    by_cadence: dict[str, int] = field(default_factory=dict)


def _amount_bucket_key(amount_cents: int) -> int:
    """Round to nearest 100 cents for grouping."""
    return round(amount_cents / 100) * 100


def _amounts_compatible(amounts: list[int]) -> bool:
    """Check all amounts are within tolerance of the median."""
    if not amounts:
        return False
    med = statistics.median(amounts)
    if med == 0:
        return all(a == 0 for a in amounts)
    return all(abs(a - med) / abs(med) <= _AMOUNT_TOLERANCE for a in amounts)


def _detect_cadence(intervals_days: list[float]) -> str | None:
    """Match interval pattern against known cadences."""
    if len(intervals_days) < 1:
        return None

    median_interval = statistics.median(intervals_days)

    if len(intervals_days) >= 2:
        mean = statistics.mean(intervals_days)
        stdev = statistics.stdev(intervals_days)
        cv = stdev / mean if mean > 0 else float("inf")
    else:
        cv = 0.0

    for cadence, min_med, max_med, max_cv, _min_count in _CADENCE_SPECS:
        if min_med <= median_interval <= max_med and cv <= max_cv:
            return cadence

    return None


async def detect_recurring(session: AsyncSession) -> DetectionResult:
    """Scan all transactions and flag recurring patterns."""
    previously_flagged = (
        await session.execute(
            select(Transaction.id).where(Transaction.is_recurring.is_(True))
        )
    ).scalars().all()

    if previously_flagged:
        await session.execute(
            update(Transaction)
            .where(Transaction.is_recurring.is_(True))
            .values(is_recurring=None, recurrence_cadence=None, recurrence_group_id=None)
        )

    stmt = (
        select(Transaction)
        .where(Transaction.description.isnot(None))
        .order_by(Transaction.posted_at)
    )
    all_txns = list((await session.execute(stmt)).scalars().all())

    payee_groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in all_txns:
        cleaned = clean_description(txn.description or "")
        normalized = normalize_for_matching(cleaned)
        if normalized:
            payee_groups[normalized].append(txn)

    result = DetectionResult()

    groups: list[RecurrenceGroup] = []

    for normalized, txns in payee_groups.items():
        if len(txns) < _MIN_GROUP_ANNUAL:
            continue

        amount_buckets: dict[int, list[Transaction]] = defaultdict(list)
        for txn in txns:
            key = _amount_bucket_key(txn.amount_cents)
            amount_buckets[key].append(txn)

        for _bucket_key, bucket_txns in amount_buckets.items():
            if len(bucket_txns) < _MIN_GROUP_ANNUAL:
                continue

            amounts = [t.amount_cents for t in bucket_txns]
            if not _amounts_compatible(amounts):
                continue

            sorted_txns = sorted(bucket_txns, key=lambda t: t.posted_at)
            intervals = []
            for i in range(1, len(sorted_txns)):
                delta = (sorted_txns[i].posted_at - sorted_txns[i - 1].posted_at).total_seconds()
                intervals.append(delta / 86400.0)

            if not intervals:
                continue

            for cadence, _min_med, _max_med, _max_cv, min_count in _CADENCE_SPECS:
                if len(sorted_txns) < min_count:
                    continue

                detected = _detect_cadence(intervals)
                if detected == cadence:
                    group_id = min(t.id for t in sorted_txns)
                    groups.append(
                        RecurrenceGroup(
                            transaction_ids=[t.id for t in sorted_txns],
                            cadence=cadence,
                            group_id=group_id,
                        )
                    )
                    break

    seen_txn_ids: set[int] = set()
    for group in groups:
        for txn_id in group.transaction_ids:
            if txn_id in seen_txn_ids:
                continue
            seen_txn_ids.add(txn_id)

    txn_by_id = {t.id: t for t in all_txns}
    for group in groups:
        result.groups_found += 1
        result.by_cadence[group.cadence] = result.by_cadence.get(group.cadence, 0) + 1
        for txn_id in group.transaction_ids:
            txn = txn_by_id.get(txn_id)
            if txn and txn_id not in seen_txn_ids or txn:
                txn.is_recurring = True
                txn.recurrence_cadence = group.cadence
                txn.recurrence_group_id = group.group_id
                result.transactions_flagged += 1

    result.transactions_cleared = len(previously_flagged)

    await session.commit()

    logger.info(
        "Recurrence detection: groups=%d flagged=%d cleared=%d cadences=%s",
        result.groups_found,
        result.transactions_flagged,
        result.transactions_cleared,
        result.by_cadence,
    )
    return result
