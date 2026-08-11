"""End-to-end categorization pipeline for bank transactions.

Orchestrates the full identity + category cascade from DESIGN_LLM_CATEGORIZATION.md:

  Identity resolution (runs first):
    Layer A: regex/heuristic cleanup of raw description
    Layer B: lookup cleaned name in Merchant table
    Layer C: LLM merchant-name guess

  Category assignment (runs on the resolved identity):
    Tier 0: exact normalized match against MemorizedRule table
    Tier 1: substring / token overlap match
    Tier 2: embedding similarity against rules vector index
    Tier 3: LLM categorization with few-shot retrieved rules

Each step is gated by the previous one failing. The pipeline returns a
result with the category assignment, confidence, source tier, resolved
merchant identity, and whether the transaction needs human review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from finance.services.embeddings import Embedder
from finance.services.merchant_resolver import (
    MerchantIdentity,
    clean_description,
    resolve_merchant_identity,
)
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
    source: str  # "memorized_rule" | "llm" | "merchant_default" | "uncategorized"
    tier: str  # "exact" | "substring" | "embedding" | "llm" | "merchant_default" | "none"
    needs_review: bool
    merchant_guess: str | None = None
    resolved_merchant: MerchantIdentity | None = None
    similar_rules: list | None = None


async def categorize(
    session: AsyncSession,
    raw_description: str,
    amount_cents: int,
    *,
    embedder: Embedder | None = None,
    skip_llm: bool = False,
) -> PipelineResult:
    """Run the full identity + categorization cascade for a single transaction.

    Pass ``embedder`` to enable Tier 2 (embedding similarity).
    Pass ``skip_llm=True`` to stop after deterministic tiers (useful for
    bulk imports where LLM calls should be deferred).
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

    # ── Identity resolution (Layers A-B-C) ──────────────────────────────
    identity = await resolve_merchant_identity(
        session, raw_description, skip_llm=skip_llm
    )

    # If identity resolved a merchant with a default_category_id and high
    # confidence, that's an auto-assign candidate before we even check rules.
    if (
        identity.default_category_id is not None
        and identity.confidence >= _AUTO_ASSIGN_CONFIDENCE
    ):
        return PipelineResult(
            category_id=identity.default_category_id,
            category_path=None,
            confidence=identity.confidence,
            source="merchant_default",
            tier="merchant_default",
            needs_review=False,
            resolved_merchant=identity,
        )

    # ── Category assignment (Tiers 0-2) ─────────────────────────────────
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
                resolved_merchant=identity,
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
                resolved_merchant=identity,
                similar_rules=rule_match.similar_rules,
            )

    # ── Tier 3: LLM categorization ──────────────────────────────────────
    if skip_llm:
        if rule_match is not None:
            return PipelineResult(
                category_id=rule_match.category_id,
                category_path=rule_match.category_path,
                confidence=rule_match.confidence,
                source="memorized_rule",
                tier=rule_match.tier,
                needs_review=True,
                resolved_merchant=identity,
                similar_rules=rule_match.similar_rules,
            )
        if identity.default_category_id is not None:
            return PipelineResult(
                category_id=identity.default_category_id,
                category_path=None,
                confidence=identity.confidence,
                source="merchant_default",
                tier="merchant_default",
                needs_review=True,
                resolved_merchant=identity,
            )
        return PipelineResult(
            category_id=None,
            category_path=None,
            confidence=0.0,
            source="uncategorized",
            tier="none",
            needs_review=True,
            resolved_merchant=identity,
        )

    similar = rule_match.similar_rules if rule_match else None

    llm_result: CategorizationResult = await categorize_transaction(
        session,
        cleaned,
        amount_cents,
        resolved_merchant=identity.resolved_name,
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
            resolved_merchant=identity,
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
        resolved_merchant=identity,
        similar_rules=similar,
    )
