"""Tier 3: LLM-based transaction categorization with few-shot retrieved rules.

Called only when Tiers 0-2 fail to resolve a category with high confidence.
Uses the same Ollama text model as the receipt categorizer but with a prompt
tuned for bank transaction descriptions and few-shot examples drawn from the
user's own memorized rules (retrieved in Tier 2).

One transaction per call — bank transactions have different merchants and
different retrieved rules each, so they can't share a single prompt the way
receipt line items do.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.config import settings
from finance.models.category import Category
from finance.services.rule_matcher import SimilarRule

logger = logging.getLogger(__name__)


@dataclass
class CategorizationResult:
    category_id: int | None
    confidence: str  # "high" | "medium" | "low"
    merchant_guess: str | None
    source: str = "llm"


def _build_category_lines(categories: list[Category]) -> str:
    by_id = {c.id: c for c in categories}
    lines = []
    for c in sorted(categories, key=lambda c: c.name.lower()):
        parts = [c.name]
        cur = c
        seen = {c.id}
        while cur.parent_id and cur.parent_id in by_id and cur.parent_id not in seen:
            cur = by_id[cur.parent_id]
            seen.add(cur.id)
            parts.append(cur.name)
        path = ":".join(reversed(parts))
        lines.append(f"{c.id}: {path}")
    return "\n".join(lines)


def _build_few_shot_block(similar_rules: list[SimilarRule]) -> str:
    if not similar_rules:
        return "No similar past transactions available."
    lines = []
    for rule in similar_rules:
        lines.append(f'"{rule.payee}" -> {rule.category_path}')
    return "\n".join(lines)


def _format_amount(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    dollars = abs(amount_cents) // 100
    cents = abs(amount_cents) % 100
    return f"{sign}${dollars}.{cents:02d}"


def _build_prompt(
    cleaned_description: str,
    amount_cents: int,
    resolved_merchant: str | None,
    similar_rules: list[SimilarRule],
    category_lines: str,
) -> str:
    few_shot = _build_few_shot_block(similar_rules)
    merchant_line = (
        f"  Resolved merchant: {resolved_merchant}"
        if resolved_merchant
        else "  Resolved merchant: unknown"
    )

    return (
        "You are categorizing a bank transaction into the user's existing category list.\n"
        "The user has categorized similar transactions before — use those examples.\n\n"
        f"Category list (id: path):\n{category_lines}\n\n"
        f"Similar past transactions (payee -> category the user chose):\n{few_shot}\n\n"
        "New transaction:\n"
        f"  Cleaned description: \"{cleaned_description}\"\n"
        f"  Amount: {_format_amount(amount_cents)}\n"
        f"{merchant_line}\n\n"
        "Respond with JSON only:\n"
        '{"category_id": <int from the list above>, '
        '"confidence": "high" | "medium" | "low", '
        '"merchant_guess": "<your best guess at the real merchant name>"}'
    )


async def _call_ollama_text(prompt: str) -> str:
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.ollama_text_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return str(resp.json().get("response", ""))


def _safe_load_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


async def categorize_transaction(
    session: AsyncSession,
    cleaned_description: str,
    amount_cents: int,
    *,
    resolved_merchant: str | None = None,
    similar_rules: list[SimilarRule] | None = None,
) -> CategorizationResult:
    """Ask the LLM to categorize a single bank transaction.

    Returns a CategorizationResult. Never raises — on any failure returns
    a low-confidence null result so the caller can punt to the user.
    """
    categories = list(
        (await session.execute(select(Category))).scalars().all()
    )
    if not categories:
        return CategorizationResult(
            category_id=None, confidence="low", merchant_guess=None
        )

    valid_ids = {c.id for c in categories}
    category_lines = _build_category_lines(categories)

    prompt = _build_prompt(
        cleaned_description,
        amount_cents,
        resolved_merchant,
        similar_rules or [],
        category_lines,
    )

    try:
        raw = await _call_ollama_text(prompt)
    except (httpx.HTTPError, Exception) as exc:
        logger.warning("Tier 3 LLM call failed: %s", exc)
        return CategorizationResult(
            category_id=None, confidence="low", merchant_guess=None
        )

    parsed = _safe_load_json(raw)

    category_id = parsed.get("category_id")
    if category_id is not None:
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            category_id = None
    if category_id not in valid_ids:
        category_id = None

    confidence = parsed.get("confidence", "low")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    merchant_guess = parsed.get("merchant_guess")
    if merchant_guess is not None:
        merchant_guess = str(merchant_guess).strip() or None

    return CategorizationResult(
        category_id=category_id,
        confidence=confidence,
        merchant_guess=merchant_guess,
    )
