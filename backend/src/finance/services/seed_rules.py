"""Import seed rules from a YAML reference file into memorized_rules.

Seed rules provide baseline merchant→category mappings for common US
merchants.  They are stored with ``source="seed"`` — the lowest priority
in ``_pick_best``, so user-created and QIF-imported rules always win.

Import is idempotent: existing seed rules are updated, higher-priority
rules are never overwritten.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.memorized_rule import MemorizedRule
from finance.services.merchant_resolver import normalize_for_matching
from finance.services.quicken import resolve_category_path

logger = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).resolve().parent.parent.parent / "data" / "seed_rules.yaml"


@dataclass
class SeedResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    missing_categories: list[str] | None = None


async def import_seed_rules(
    session: AsyncSession,
    yaml_path: Path | None = None,
) -> SeedResult:
    """Load seed rules from YAML and upsert into the database."""
    path = yaml_path or _DEFAULT_YAML
    with open(path) as f:
        data = yaml.safe_load(f)

    entries = data.get("rules", [])
    if not entries:
        return SeedResult()

    existing_stmt = select(MemorizedRule).where(MemorizedRule.status != "inactive")
    existing_rules = (await session.execute(existing_stmt)).scalars().all()

    rules_by_normalized: dict[str, MemorizedRule] = {}
    for r in existing_rules:
        rules_by_normalized.setdefault(r.normalized_payee, r)

    result = SeedResult(missing_categories=[])

    for entry in entries:
        payee = entry["payee"]
        category_path = entry["category_path"]
        normalized = normalize_for_matching(payee)

        if not normalized:
            continue

        existing = rules_by_normalized.get(normalized)

        if existing and existing.source in ("user_created", "qif_import"):
            result.skipped += 1
            continue

        cat = await resolve_category_path(session, category_path)
        category_id = cat.id if cat else None
        if cat is None and category_path not in result.missing_categories:
            result.missing_categories.append(category_path)

        if existing and existing.source == "seed":
            existing.category_path = category_path
            existing.category_id = category_id
            existing.payee = payee
            result.updated += 1
        else:
            rule = MemorizedRule(
                payee=payee,
                normalized_payee=normalized,
                category_path=category_path,
                category_id=category_id,
                kind="payment",
                source="seed",
                status="active",
            )
            session.add(rule)
            rules_by_normalized[normalized] = rule
            result.created += 1

    await session.commit()

    if not result.missing_categories:
        result.missing_categories = None

    logger.info(
        "Seed rules: created=%d updated=%d skipped=%d missing_categories=%s",
        result.created,
        result.updated,
        result.skipped,
        result.missing_categories,
    )
    return result
