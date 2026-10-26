"""History tier for the categorization pipeline.

Looks at how the user has already categorized transactions with the same
cleaned description and suggests the most common category. This is a
suggestion source, not a rule: confidence stays below the auto-assign
threshold so every history match goes through review. Confirming a
suggestion via ``/apply-categories`` creates a MemorizedRule, so history
matches graduate into rules over time.

Build the index once per request with ``build_history_index`` and pass it
to ``categorization_pipeline.categorize``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.category import Category
from finance.models.transaction import Transaction
from finance.services.merchant_resolver import clean_description, normalize_for_matching

# Categories that say nothing about what a merchant is.
_EXCLUDED_CATEGORY_NAMES = ("Uncategorized", "Transfer")

# Below this share of past occurrences, the history is too mixed to suggest.
_MIN_AGREEMENT = 0.5
# Occurrences needed before history reaches its maximum confidence.
_FULL_WEIGHT_COUNT = 5
_MAX_CONFIDENCE = 0.90


@dataclass
class HistoryMatch:
    category_id: int
    count: int  # past transactions with this description
    agreement: float  # share of those that used category_id
    confidence: float


def history_key(description: str) -> str:
    cleaned = clean_description(description)
    return normalize_for_matching(cleaned or description)


class HistoryIndex:
    def __init__(self, counts: dict[str, Counter[int]]):
        self._counts = counts

    def __len__(self) -> int:
        return len(self._counts)

    def match(self, description: str) -> HistoryMatch | None:
        key = history_key(description)
        counter = self._counts.get(key) if key else None
        if not counter:
            return None

        category_id, hits = counter.most_common(1)[0]
        total = sum(counter.values())
        agreement = hits / total
        if agreement < _MIN_AGREEMENT:
            return None

        weight = min(total, _FULL_WEIGHT_COUNT) / _FULL_WEIGHT_COUNT
        confidence = round(0.5 + (_MAX_CONFIDENCE - 0.5) * agreement * weight, 2)
        return HistoryMatch(
            category_id=category_id,
            count=total,
            agreement=agreement,
            confidence=confidence,
        )


async def build_history_index(session: AsyncSession) -> HistoryIndex:
    """Index confirmed, non-transfer transactions by normalized description."""
    excluded_ids = (
        await session.execute(
            select(Category.id).where(Category.name.in_(_EXCLUDED_CATEGORY_NAMES))
        )
    ).scalars().all()

    stmt = (
        select(Transaction.description, Transaction.category_id)
        .where(Transaction.category_id.isnot(None))
        # Unconfirmed suggestions would let history reinforce its own guesses.
        .where(Transaction.needs_review.is_(False))
        .where(Transaction.description.isnot(None))
        .where(Transaction.transfer_pair_id.is_(None))
        .where(Transaction.transfer_target_account_id.is_(None))
    )
    if excluded_ids:
        stmt = stmt.where(Transaction.category_id.notin_(excluded_ids))

    counts: dict[str, Counter[int]] = {}
    for description, category_id in (await session.execute(stmt)).all():
        key = history_key(description)
        if key:
            counts.setdefault(key, Counter())[category_id] += 1
    return HistoryIndex(counts)
