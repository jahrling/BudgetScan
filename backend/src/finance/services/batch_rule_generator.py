"""Batch LLM rule generation: group uncategorized transactions and ask the
model to produce *rules* rather than per-transaction assignments.

One LLM call per batch of 10-20 similar descriptions. Results are
``status="draft"`` MemorizedRules for user review.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.category import Category
from finance.models.memorized_rule import MemorizedRule
from finance.models.transaction import Transaction
from finance.services.merchant_resolver import clean_description, normalize_for_matching
from finance.services.rule_matcher import match_rule
from finance.services.transaction_categorizer import (
    _build_category_lines,
    _call_ollama_text,
    _format_amount,
    _safe_load_json,
)

logger = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 20
_MIN_GROUP_SIZE = 3


@dataclass
class BatchRuleResult:
    drafts_created: int = 0
    batches_processed: int = 0
    transactions_covered: int = 0
    errors: list[str] = field(default_factory=list)


def _first_token(cleaned: str) -> str:
    """Extract first significant word for grouping."""
    parts = cleaned.lower().split()
    return parts[0] if parts else ""


def _build_batch_prompt(
    descriptions: list[tuple[str, int]],
    category_lines: str,
    sample_rules: list[MemorizedRule],
) -> str:
    rule_block = "\n".join(
        f'  "{r.payee}" -> {r.category_path}'
        for r in sample_rules[:20]
    ) or "  (none yet)"

    txn_block = "\n".join(
        f'  {i+1}. "{desc}" — {_format_amount(amt)}'
        for i, (desc, amt) in enumerate(descriptions)
    )

    return (
        "You are analyzing bank transaction descriptions to create categorization RULES.\n"
        "A rule maps a merchant/payee pattern to a category so all future transactions\n"
        "matching that pattern are auto-categorized.\n\n"
        f"Category list (id: path):\n{category_lines}\n\n"
        f"Existing rules (for reference):\n{rule_block}\n\n"
        f"Transactions to analyze (all uncategorized):\n{txn_block}\n\n"
        "For each distinct merchant/payee you identify, suggest a rule.\n"
        "Rules should be general enough to match future transactions from the same\n"
        "merchant, but specific enough to avoid false positives.\n\n"
        "Respond with JSON only — a JSON array:\n"
        '[{"payee": "Merchant Name", "category_id": <int from list>, "confidence": "high"|"medium"|"low"}]\n'
    )


async def generate_rules_from_batch(
    session: AsyncSession,
    transaction_ids: list[int] | None = None,
) -> BatchRuleResult:
    """Batch uncategorized transactions and generate draft rules via LLM."""
    stmt = select(Transaction).where(
        Transaction.category_id.is_(None),
        Transaction.description.isnot(None),
    )
    if transaction_ids:
        stmt = stmt.where(Transaction.id.in_(transaction_ids))

    transactions = list((await session.execute(stmt)).scalars().all())

    unmatched: list[tuple[Transaction, str]] = []
    for txn in transactions:
        cleaned = clean_description(txn.description or "")
        if not cleaned:
            continue
        existing = await match_rule(session, cleaned)
        if existing and existing.confidence >= 0.85:
            continue
        unmatched.append((txn, cleaned))

    if not unmatched:
        return BatchRuleResult()

    groups: dict[str, list[tuple[Transaction, str]]] = defaultdict(list)
    for txn, cleaned in unmatched:
        token = _first_token(cleaned)
        groups[token].append((txn, cleaned))

    categories = list((await session.execute(select(Category))).scalars().all())
    valid_ids = {c.id for c in categories}
    category_lines = _build_category_lines(categories)

    sample_stmt = (
        select(MemorizedRule)
        .where(MemorizedRule.status == "active")
        .limit(20)
    )
    sample_rules = list((await session.execute(sample_stmt)).scalars().all())

    existing_normalized = set(
        (await session.execute(
            select(MemorizedRule.normalized_payee)
            .where(MemorizedRule.status.in_(["active", "draft"]))
        )).scalars().all()
    )

    result = BatchRuleResult()

    for token, group_entries in groups.items():
        if len(group_entries) < _MIN_GROUP_SIZE:
            continue

        batch = group_entries[:_MAX_BATCH_SIZE]
        descriptions = [(cleaned, txn.amount_cents) for txn, cleaned in batch]

        prompt = _build_batch_prompt(descriptions, category_lines, sample_rules)

        try:
            raw = await _call_ollama_text(prompt)
        except Exception as exc:
            logger.warning("Batch LLM call failed for group %r: %s", token, exc)
            result.errors.append(f"LLM error for group '{token}': {str(exc)[:100]}")
            continue

        result.batches_processed += 1
        result.transactions_covered += len(batch)

        parsed = _safe_load_json(raw)
        suggestions: list[dict] = []
        if isinstance(parsed, dict) and "payee" in parsed:
            suggestions = [parsed]
        elif isinstance(parsed, list):
            suggestions = parsed
        else:
            raw_text = raw.strip()
            start = raw_text.find("[")
            end = raw_text.rfind("]")
            if start != -1 and end > start:
                try:
                    suggestions = json.loads(raw_text[start:end + 1])
                except json.JSONDecodeError:
                    pass

        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue

            payee = suggestion.get("payee")
            category_id = suggestion.get("category_id")

            if not payee or category_id is None:
                continue

            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                continue

            if category_id not in valid_ids:
                continue

            normalized = normalize_for_matching(str(payee))
            if not normalized or normalized in existing_normalized:
                continue

            cat_row = (
                await session.execute(
                    select(Category).where(Category.id == category_id)
                )
            ).scalar_one_or_none()

            category_path = ""
            if cat_row:
                parts = [cat_row.name]
                parent = cat_row.parent
                while parent is not None:
                    parts.append(parent.name)
                    parent = parent.parent
                category_path = ":".join(reversed(parts))

            rule = MemorizedRule(
                payee=str(payee),
                normalized_payee=normalized,
                category_path=category_path,
                category_id=category_id,
                kind="payment",
                source="llm_batch",
                status="draft",
            )
            session.add(rule)
            existing_normalized.add(normalized)
            result.drafts_created += 1

    await session.commit()

    logger.info(
        "Batch rule generation: batches=%d txns=%d drafts=%d errors=%d",
        result.batches_processed,
        result.transactions_covered,
        result.drafts_created,
        len(result.errors),
    )
    return result
