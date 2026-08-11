"""End-to-end categorization pipeline for bank transactions.

Orchestrates the full Tier 0-3 cascade described in DESIGN_LLM_CATEGORIZATION.md:

  1. Layer A: regex/heuristic cleanup of raw description
  2. Tier 0: exact normalized match against MemorizedRule table
  3. Tier 1: substring / token overlap match
  4. Tier 2: embedding similarity against rules vector index
  5. Tier 3: LLM categorization with few-shot retrieved rules

Each tier is gated by the previous one failing. The pipeline returns a
result with the category assignment, confidence, source tier, and whether
the transaction needs human review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from finance.services.embeddings import Embedder
from finance.services.merchant_resolver import clean_description
from finance.services.rule_matcher import RuleMatch, match_rule
from finance.services.transaction_categorizer import (
    CategorizationResult,
    categorize_transaction,
)

logger = logging.getLogger(__name__)

_AUTO_ASSIGN_CONFIDENCE = 0.92


@dataclass
class PipelineResult:
    category_id: int | None
    category_path: str | None
    confidence: float
    source: str  # "memorized_rule" | "llm" | "uncategorized"
    tier: str  # "exact" | "substring" | "embedding" | "llm" | "none"
    needs_review: bool
    merchant_guess: str | None = None
    similar_rules: list | None = None


async def categorize(
    session: AsyncSession,
    raw_description: str,
    amount_cents: int,
    *,
    resolved_merchant: str | None = None,
    embedder: Embedder | None = None,
    skip_llm: bool = False,
) -> PipelineResult:
    """Run the full categorization cascade for a single transaction.

    Pass ``embedder`` to enable Tier 2 (embedding similarity).
    Pass ``skip_llm=True`` to stop after Tier 2 (useful for bulk imports
    where LLM calls should be deferred to avoid GPU contention).
    """
    cleaned = clean_description(raw_description)
    if not cleaned:
        return PipelineResult(
            category_id=None,
            category_path=None,
            confidence=0.0,
            source="uncategorized",
            tier="none",
            needs_review=True,
        )

    # Tiers 0-2
    rule_match = await match_rule(session, cleaned, embedder=embedder)

    if rule_match is not None:
        if rule_match.confidence >= _AUTO_ASSIGN_CONFIDENCE:
            return PipelineResult(
                category_id=rule_match.category_id,
                category_path=rule_match.category_path,
                confidence=rule_match.confidence,
                source="memorized_rule",
                tier=rule_match.tier,
                needs_review=False,
                similar_rules=rule_match.similar_rules,
            )

        if rule_match.tier in ("exact", "substring"):
            return PipelineResult(
                category_id=rule_match.category_id,
                category_path=rule_match.category_path,
                confidence=rule_match.confidence,
                source="memorized_rule",
                tier=rule_match.tier,
                needs_review=True,
                similar_rules=rule_match.similar_rules,
            )

    # Tier 3: LLM categorization
    if skip_llm:
        if rule_match is not None:
            return PipelineResult(
                category_id=rule_match.category_id,
                category_path=rule_match.category_path,
                confidence=rule_match.confidence,
                source="memorized_rule",
                tier=rule_match.tier,
                needs_review=True,
                similar_rules=rule_match.similar_rules,
            )
        return PipelineResult(
            category_id=None,
            category_path=None,
            confidence=0.0,
            source="uncategorized",
            tier="none",
            needs_review=True,
        )

    similar = rule_match.similar_rules if rule_match else None

    llm_result: CategorizationResult = await categorize_transaction(
        session,
        cleaned,
        amount_cents,
        resolved_merchant=resolved_merchant,
        similar_rules=similar,
    )

    if llm_result.category_id is None:
        return PipelineResult(
            category_id=None,
            category_path=None,
            confidence=0.0,
            source="uncategorized",
            tier="llm",
            needs_review=True,
            merchant_guess=llm_result.merchant_guess,
            similar_rules=similar,
        )

    needs_review = llm_result.confidence != "high"
    confidence_map = {"high": 0.90, "medium": 0.75, "low": 0.50}
    confidence = confidence_map.get(llm_result.confidence, 0.50)

    return PipelineResult(
        category_id=llm_result.category_id,
        category_path=None,
        confidence=confidence,
        source="llm",
        tier="llm",
        needs_review=needs_review,
        merchant_guess=llm_result.merchant_guess,
        similar_rules=similar,
    )
