"""Generate draft MemorizedRules from user-confirmed transaction patterns.

Groups transactions with ``category_source="user"`` by normalized payee.
Payees with 2+ consistent categorizations (same category, no conflicts)
become ``status="draft"`` rules for user review.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.category import Category
from finance.models.memorized_rule import MemorizedRule
from finance.models.transaction import Transaction
from finance.services.merchant_resolver import clean_description, normalize_for_matching

logger = logging.getLogger(__name__)

_MIN_CONSISTENT_COUNT = 2


@dataclass
class ConflictInfo:
    payee: str
    category_ids: list[int]
    transaction_count: int


@dataclass
class DraftGenerationResult:
    drafts_created: int = 0
    skipped_existing: int = 0
    conflicts: list[ConflictInfo] = field(default_factory=list)


async def generate_draft_rules(session: AsyncSession) -> DraftGenerationResult:
    """Analyze user-categorized transactions and create draft rules."""
    stmt = (
        select(Transaction)
        .where(Transaction.category_source == "user")
        .where(Transaction.category_id.isnot(None))
        .where(Transaction.description.isnot(None))
    )
    transactions = (await session.execute(stmt)).scalars().all()

    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for txn in transactions:
        cleaned = clean_description(txn.description)
        normalized = normalize_for_matching(cleaned)
        if not normalized:
            continue
        groups[normalized].append((cleaned, txn.category_id))

    active_stmt = (
        select(MemorizedRule.normalized_payee)
        .where(MemorizedRule.status.in_(["active", "draft"]))
    )
    existing_normalized = set(
        (await session.execute(active_stmt)).scalars().all()
    )

    result = DraftGenerationResult()

    for normalized, entries in groups.items():
        if len(entries) < _MIN_CONSISTENT_COUNT:
            continue

        if normalized in existing_normalized:
            result.skipped_existing += 1
            continue

        category_ids = {cat_id for _, cat_id in entries}
        if len(category_ids) > 1:
            result.conflicts.append(
                ConflictInfo(
                    payee=entries[0][0],
                    category_ids=sorted(category_ids),
                    transaction_count=len(entries),
                )
            )
            continue

        category_id = category_ids.pop()

        cleaned_names = [name for name, _ in entries]
        payee = Counter(cleaned_names).most_common(1)[0][0]

        cat_stmt = select(Category).where(Category.id == category_id)
        cat_row = (await session.execute(cat_stmt)).scalar_one_or_none()

        category_path = ""
        if cat_row is not None:
            parts = [cat_row.name]
            parent = cat_row.parent
            while parent is not None:
                parts.append(parent.name)
                parent = parent.parent
            category_path = ":".join(reversed(parts))

        rule = MemorizedRule(
            payee=payee,
            normalized_payee=normalized,
            category_path=category_path,
            category_id=category_id,
            kind="payment",
            source="auto_draft",
            status="draft",
        )
        session.add(rule)
        existing_normalized.add(normalized)
        result.drafts_created += 1

    await session.commit()

    logger.info(
        "Draft rule generation: created=%d skipped=%d conflicts=%d",
        result.drafts_created,
        result.skipped_existing,
        len(result.conflicts),
    )
    return result
