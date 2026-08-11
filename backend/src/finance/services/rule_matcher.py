"""Rule matching (Tiers 0-2) for the categorization pipeline.

Tier 0 -- exact normalized match against the ``MemorizedRule`` table.
Tier 1 -- substring / token-overlap fallback when Tier 0 misses.
Tier 2 -- embedding similarity against a local vector index of rule payees.

Tiers 0-1 are pure DB + string operations with zero model involvement.
Tier 2 requires an ``Embedder`` and the rules vector index built by
``vector_store.rebuild_rules_index``.

Usage::

    result = await match_rule(session, cleaned_description, embedder=embedder)
    if result:
        print(f"Matched rule {result.rule_id} at tier={result.tier}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.memorized_rule import MemorizedRule
from finance.services.embeddings import Embedder
from finance.services.merchant_resolver import normalize_for_matching
from finance.services.vector_store import VectorStore, rules_index_path

logger = logging.getLogger(__name__)

# Minimum character length for a substring/token match to count.
_MIN_MATCH_LENGTH = 5

_TIER2_HIGH_THRESHOLD = 0.92
_TIER2_MIN_THRESHOLD = 0.70


@dataclass
class RuleMatch:
    """Result of a successful rule match."""

    rule_id: int
    category_id: int | None
    category_path: str
    tier: str  # "exact" | "substring" | "embedding"
    confidence: float
    similar_rules: list[SimilarRule] | None = None


@dataclass
class SimilarRule:
    """A memorized rule retrieved via embedding similarity (Tier 2)."""

    rule_id: int
    payee: str
    category_path: str
    category_id: int | None
    score: float


async def match_rule(
    session: AsyncSession,
    cleaned_description: str,
    *,
    embedder: Embedder | None = None,
) -> RuleMatch | None:
    """Try to match *cleaned_description* against memorized rules.

    Returns the best ``RuleMatch`` if one is found, or ``None``.

    Resolution order:
      1. Tier 0 -- exact normalized match (confidence 1.0)
      2. Tier 1 -- substring / token overlap (confidence 0.85)
      3. Tier 2 -- embedding similarity against rules index

    When Tier 2 finds a high-confidence match (>= 0.92) it returns
    directly.  For moderate matches it returns the top-k similar rules
    as ``similar_rules`` for use as few-shot context in Tier 3.
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
    result = await _tier1_substring(session, normalized)
    if result is not None:
        return result

    # ------------------------------------------------------------------
    # Tier 2: embedding similarity
    # ------------------------------------------------------------------
    if embedder is not None:
        return await _tier2_embedding(session, cleaned_description, embedder)

    return None


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


async def _tier2_embedding(
    session: AsyncSession,
    cleaned_description: str,
    embedder: Embedder,
) -> RuleMatch | None:
    """Tier 2: embed the description and search the rules vector index."""
    index_path = rules_index_path()
    if not index_path.exists():
        logger.debug("Tier 2: rules index not found at %s", index_path)
        return None

    store = VectorStore(path=index_path).load()
    if len(store) == 0:
        return None

    vecs = await embedder.embed([cleaned_description])
    query_vec = vecs[0]

    hits = store.search(query_vec, k=8)
    if not hits or hits[0].score < _TIER2_MIN_THRESHOLD:
        return None

    hit_rule_ids = [h.ref_id for h in hits if h.score >= _TIER2_MIN_THRESHOLD]
    if not hit_rule_ids:
        return None

    stmt = (
        select(MemorizedRule)
        .where(MemorizedRule.id.in_(hit_rule_ids))
        .where(MemorizedRule.status == "active")
    )
    rules_by_id = {
        r.id: r for r in (await session.execute(stmt)).scalars().all()
    }

    similar: list[SimilarRule] = []
    for hit in hits:
        rule = rules_by_id.get(hit.ref_id)
        if rule is None:
            continue
        similar.append(
            SimilarRule(
                rule_id=rule.id,
                payee=rule.payee,
                category_path=rule.category_path,
                category_id=rule.category_id,
                score=hit.score,
            )
        )

    if not similar:
        return None

    best = similar[0]

    if best.score >= _TIER2_HIGH_THRESHOLD:
        logger.debug(
            "Tier 2 high-confidence match: rule %d (score=%.3f) for %r",
            best.rule_id,
            best.score,
            cleaned_description,
        )
        return RuleMatch(
            rule_id=best.rule_id,
            category_id=best.category_id,
            category_path=best.category_path,
            tier="embedding",
            confidence=best.score,
            similar_rules=similar,
        )

    logger.debug(
        "Tier 2 moderate matches: top score=%.3f for %r, returning %d similar rules",
        best.score,
        cleaned_description,
        len(similar),
    )
    return RuleMatch(
        rule_id=best.rule_id,
        category_id=best.category_id,
        category_path=best.category_path,
        tier="embedding",
        confidence=best.score,
        similar_rules=similar,
    )
