"""Deterministic rule matching (Tiers 0-1) for the categorization pipeline.

Tier 0 -- exact normalized match against the ``MemorizedRule`` table.
Tier 1 -- substring / token-overlap fallback when Tier 0 misses.

Both tiers are pure DB + string operations with zero model involvement.
Together they should resolve the majority of recurring transactions before
any embedding or LLM tier is invoked.

Usage::

    result = await match_rule(session, cleaned_description)
    if result:
        print(f"Matched rule {result.rule_id} at tier={result.tier}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.memorized_rule import MemorizedRule
from finance.services.merchant_resolver import normalize_for_matching

logger = logging.getLogger(__name__)

# Minimum character length for a substring/token match to count.
_MIN_MATCH_LENGTH = 5


@dataclass
class RuleMatch:
    """Result of a successful rule match."""

    rule_id: int
    category_id: int | None
    category_path: str
    tier: str  # "exact" | "substring"
    confidence: float


async def match_rule(
    session: AsyncSession,
    cleaned_description: str,
) -> RuleMatch | None:
    """Try to match *cleaned_description* against memorized rules.

    Returns the best ``RuleMatch`` if one is found, or ``None``.

    Resolution order:
      1. Tier 0 -- exact normalized match (confidence 1.0)
      2. Tier 1 -- substring / token overlap (confidence 0.85)

    >>> # (requires a live DB session with rules loaded)
    >>> result = await match_rule(session, "Costco")
    >>> result.tier
    'exact'
    """
    normalized = normalize_for_matching(cleaned_description)
    if not normalized:
        return None

    # ------------------------------------------------------------------
    # Tier 0: exact normalized match
    # ------------------------------------------------------------------
    result = await _tier0_exact(session, normalized)
    if result is not None:
        return result

    # ------------------------------------------------------------------
    # Tier 1: substring / token overlap
    # ------------------------------------------------------------------
    return await _tier1_substring(session, normalized)


async def _tier0_exact(
    session: AsyncSession,
    normalized: str,
) -> RuleMatch | None:
    """Tier 0: exact match on ``normalized_payee``."""
    stmt = (
        select(MemorizedRule)
        .where(MemorizedRule.normalized_payee == normalized)
        .where(MemorizedRule.status == "active")
    )
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return None

    rule = _pick_best(rows)
    logger.debug("Tier 0 exact match: rule %d for %r", rule.id, normalized)
    return RuleMatch(
        rule_id=rule.id,
        category_id=rule.category_id,
        category_path=rule.category_path,
        tier="exact",
        confidence=1.0,
    )


async def _tier1_substring(
    session: AsyncSession,
    normalized: str,
) -> RuleMatch | None:
    """Tier 1: substring containment or dominant-token overlap."""
    stmt = select(MemorizedRule).where(MemorizedRule.status == "active")
    rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return None

    best_rule: MemorizedRule | None = None
    best_overlap = 0

    input_tokens = set(normalized.split())

    for rule in rows:
        rp = rule.normalized_payee

        # Substring containment (either direction).
        if len(rp) >= _MIN_MATCH_LENGTH and rp in normalized:
            overlap = len(rp)
        elif len(normalized) >= _MIN_MATCH_LENGTH and normalized in rp:
            overlap = len(normalized)
        else:
            # Token overlap: shared tokens of length >= 5.
            rule_tokens = set(rp.split())
            shared = {
                t for t in input_tokens & rule_tokens if len(t) >= _MIN_MATCH_LENGTH
            }
            overlap = sum(len(t) for t in shared)

        if overlap >= _MIN_MATCH_LENGTH and overlap > best_overlap:
            best_overlap = overlap
            best_rule = rule

    if best_rule is None:
        return None

    logger.debug(
        "Tier 1 substring match: rule %d (overlap=%d) for %r",
        best_rule.id,
        best_overlap,
        normalized,
    )
    return RuleMatch(
        rule_id=best_rule.id,
        category_id=best_rule.category_id,
        category_path=best_rule.category_path,
        tier="substring",
        confidence=0.85,
    )


def _pick_best(rules: list[MemorizedRule] | list) -> MemorizedRule:
    """From multiple matching rules, pick the best one.

    Preference order:
      1. Has a resolved ``category_id`` (non-null).
      2. Source ``"user_created"`` over ``"qif_import"``.
      3. Most recently updated (highest ``id`` as tiebreaker).
    """
    if len(rules) == 1:
        return rules[0]

    def sort_key(r: MemorizedRule) -> tuple[bool, bool, int]:
        has_category = r.category_id is not None
        is_user = r.source == "user_created"
        return (has_category, is_user, r.id)

    return max(rules, key=sort_key)
