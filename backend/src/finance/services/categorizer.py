"""Suggest a category_id for each line item on a parsed receipt.

Two-step strategy:
  1. If the receipt has a merchant with a `default_category_id`, every item
     defaults to that.
  2. Call the text LLM with the category tree + line items, asking for a
     JSON map of {description: category_id}. Per-item suggestions override
     the merchant default.

The LLM call is best-effort: any error falls back to step-1 / Uncategorized
so the user is never blocked.

Results are cached by (normalized_description, category_set_hash) for the
lifetime of the process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.config import settings
from finance.models.category import Category
from finance.models.merchant import Merchant
from finance.services.transaction import _get_or_create_uncategorized

logger = logging.getLogger(__name__)

# {(normalized_desc, category_set_hash): category_id}
_CACHE: dict[tuple[str, str], int] = {}


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _category_set_hash(categories: list[Category]) -> str:
    payload = ",".join(f"{c.id}:{c.name}" for c in sorted(categories, key=lambda c: c.id))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _build_category_lines(categories: list[Category]) -> str:
    by_id = {c.id: c for c in categories}
    lines = []
    for c in sorted(categories, key=lambda c: c.name.lower()):
        # Walk up to construct a path like "Food > Groceries"
        parts = [c.name]
        cur = c
        seen = {c.id}
        while cur.parent_id and cur.parent_id in by_id and cur.parent_id not in seen:
            cur = by_id[cur.parent_id]
            seen.add(cur.id)
            parts.append(cur.name)
        path = " > ".join(reversed(parts))
        lines.append(f"{c.id}: {path}")
    return "\n".join(lines)


async def _list_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category))
    return list(result.scalars().all())


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


async def suggest_categories(
    session: AsyncSession,
    items: list[dict[str, Any]],
    *,
    merchant: Merchant | None = None,
) -> list[int]:
    """Return one suggested category_id per item, in input order.

    Never raises: on any failure, returns Uncategorized for unresolved items.
    """
    categories = await _list_categories(session)
    valid_ids = {c.id for c in categories}

    # Merchant default takes priority for any item we don't otherwise resolve.
    default_id: int | None = None
    if merchant and merchant.default_category_id in valid_ids:
        default_id = merchant.default_category_id

    cat_set_hash = _category_set_hash(categories)

    # Resolve from cache where possible.
    descriptions = [_normalize(str(it.get("description") or "")) for it in items]
    suggestions: list[int | None] = [
        _CACHE.get((d, cat_set_hash)) if d else None for d in descriptions
    ]

    needs_llm_idx = [i for i, s in enumerate(suggestions) if s is None and descriptions[i]]
    if needs_llm_idx and categories:
        try:
            llm_map = await _llm_suggest(
                categories,
                [items[i] for i in needs_llm_idx],
            )
            for i in needs_llm_idx:
                desc = descriptions[i]
                cid = llm_map.get(desc) or llm_map.get(str(items[i].get("description") or ""))
                if cid in valid_ids:
                    suggestions[i] = cid
                    _CACHE[(desc, cat_set_hash)] = cid
        except Exception as exc:  # noqa: BLE001 — categorizer is best-effort
            logger.warning("Categorizer LLM call failed: %s", exc)

    uncategorized = await _get_or_create_uncategorized(session)
    # Refresh cat list if Uncategorized was just created so the id is valid.
    if uncategorized.id not in valid_ids:
        valid_ids.add(uncategorized.id)

    final: list[int] = []
    for s in suggestions:
        if s in valid_ids and s is not None:
            final.append(s)
        elif default_id is not None:
            final.append(default_id)
        else:
            final.append(uncategorized.id)
    return final


async def _llm_suggest(
    categories: list[Category],
    items: list[dict[str, Any]],
) -> dict[str, int]:
    if not items:
        return {}
    cat_block = _build_category_lines(categories)
    item_block = "\n".join(
        f"- {it.get('description', '')}" for it in items if it.get("description")
    )
    prompt = (
        "You are categorizing receipt line items into the user's existing "
        "category list. For each item, pick the single best category by id.\n\n"
        f"Categories (id: path):\n{cat_block}\n\n"
        f"Items:\n{item_block}\n\n"
        "Respond with a JSON object mapping each item's description (verbatim, "
        "lowercased, whitespace-collapsed) to the integer category id you chose. "
        "Use only ids from the list above. JSON only, no commentary.\n"
        "Example: {\"milk 1 gal\": 12, \"paper towels\": 7}"
    )
    try:
        raw = await _call_ollama_text(prompt)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error: {exc}") from exc

    parsed = _safe_load_map(raw)
    out: dict[str, int] = {}
    for k, v in parsed.items():
        try:
            out[_normalize(str(k))] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _safe_load_map(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        # Drop the first/last code fence lines.
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


def clear_cache() -> None:
    """Test helper."""
    _CACHE.clear()
