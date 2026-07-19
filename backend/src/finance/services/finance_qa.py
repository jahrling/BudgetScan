"""Finance Q&A orchestrator: route, then retrieve.

This is the public entry point for the summarization/RAG layer. It applies the
ADR-0003 boundary:

    numeric / aggregation intent  -> SQL against SQLite (exact cents)
    free-text / "why" intent      -> vector retrieval over prose + generation

The two paths are mutually exclusive per query. A query classified as numeric
NEVER embeds or touches the vector store; a query classified as free-text NEVER
runs an aggregation. Dependencies (embedder, vector store, generator) are
injectable so the boundary and each path are testable without a live Ollama.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.config import settings
from finance.models.category import Category
from finance.services import aggregation
from finance.services.embeddings import Embedder, default_embedder
from finance.services.query_router import Route, classify_intent
from finance.services.vector_store import SearchHit, VectorStore

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_QUARTERS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}


class Generator(Protocol):
    async def generate(self, query: str, hits: list[SearchHit]) -> str: ...


@dataclass
class Answer:
    route: Route
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    sources: list[SearchHit] = field(default_factory=list)
    reason: str = ""


# --------------------------------------------------------------------------
# Period + category extraction for the SQL path (deterministic, no clock dep
# unless a bare quarter/month is used without a year).
# --------------------------------------------------------------------------

def _month_bounds(year: int, month_from: int, month_to: int) -> tuple[datetime, datetime]:
    start = datetime(year, month_from, 1, tzinfo=timezone.utc)
    if month_to == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month_to + 1, 1, tzinfo=timezone.utc)
    return start, end


def parse_period(query: str) -> tuple[datetime | None, datetime | None]:
    """Best-effort date window from a query. Returns (from, to) half-open-ish.

    Recognises: `QN YYYY`, `<Month> YYYY`, and a bare 4-digit `YYYY`. A quarter
    or month without a year yields no window (all-time) rather than guessing.
    """
    text = query.lower()
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None

    q_match = re.search(r"\bq([1-4])\b", text)
    if q_match and year is not None:
        m_from, m_to = _QUARTERS[int(q_match.group(1))]
        return _month_bounds(year, m_from, m_to)

    for name, mnum in _MONTHS.items():
        if re.search(rf"\b{name}\b", text) and year is not None:
            return _month_bounds(year, mnum, mnum)

    if year is not None:
        return _month_bounds(year, 1, 12)

    return None, None


async def _match_category(session: AsyncSession, query: str) -> Category | None:
    """Return the category whose name appears in the query, longest name first."""
    rows = await session.execute(select(Category))
    cats = sorted(rows.scalars().all(), key=lambda c: len(c.name), reverse=True)
    text = query.lower()
    for c in cats:
        if re.search(rf"\b{re.escape(c.name.lower())}\b", text):
            return c
    return None


def _fmt_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

async def answer(
    session: AsyncSession,
    query: str,
    *,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    generator: Generator | None = None,
    k: int = 5,
) -> Answer:
    intent = classify_intent(query)
    if intent.route is Route.SQL:
        return await _answer_sql(session, query, reason=intent.reason)
    return await _answer_vector(
        session,
        query,
        embedder=embedder,
        store=store,
        generator=generator,
        k=k,
        reason=intent.reason,
    )


async def _answer_sql(session: AsyncSession, query: str, *, reason: str) -> Answer:
    date_from, date_to = parse_period(query)
    category = await _match_category(session, query)

    if category is not None:
        cents = await aggregation.spend_for_category_name(
            session, category.name, date_from=date_from, date_to=date_to
        )
        scope = category.name
    else:
        cents = await aggregation.total_spend(
            session, date_from=date_from, date_to=date_to
        )
        scope = "all categories"

    period = _describe_period(date_from, date_to)
    text = f"You spent {_fmt_cents(cents)} on {scope}{period}."
    return Answer(
        route=Route.SQL,
        text=text,
        data={
            "amount_cents": cents,
            "category": category.name if category else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        reason=reason,
    )


def _describe_period(date_from: datetime | None, date_to: datetime | None) -> str:
    if date_from is None and date_to is None:
        return ""
    if date_from is not None and date_to is not None:
        return f" between {date_from.date()} and {date_to.date()}"
    if date_from is not None:
        return f" since {date_from.date()}"
    return f" through {date_to.date()}"  # type: ignore[union-attr]


async def _answer_vector(
    session: AsyncSession,
    query: str,
    *,
    embedder: Embedder | None,
    store: VectorStore | None,
    generator: Generator | None,
    k: int,
    reason: str,
) -> Answer:
    embedder = embedder or default_embedder()
    if store is None:
        store = VectorStore().load()
    generator = generator or OllamaGenerator()

    query_vec = (await embedder.embed([query]))[0]
    hits = store.search(query_vec, k=k)

    if not hits:
        return Answer(
            route=Route.VECTOR,
            text="I couldn't find any notes related to that.",
            sources=[],
            reason=reason,
        )

    text = await generator.generate(query, hits)
    return Answer(route=Route.VECTOR, text=text, sources=hits, reason=reason)


class OllamaGenerator:
    """Summarise retrieved prose with the local text model. Prose in, prose out.

    The prompt forbids inventing figures — any number the user needs comes from
    the SQL path, not from generation over notes.
    """

    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self._base_url = (base_url or settings.ollama_url).rstrip("/")
        self._model = model or settings.ollama_text_model

    async def generate(self, query: str, hits: list[SearchHit]) -> str:
        import httpx

        notes = "\n".join(f"- {h.text}" for h in hits)
        prompt = (
            "Answer the user's question using ONLY the notes below. These are "
            "the user's own annotations and receipt line items. Do not invent "
            "dollar amounts or totals — if a number is asked for, say it must be "
            "looked up in the transaction records.\n\n"
            f"Notes:\n{notes}\n\n"
            f"Question: {query}\n\nAnswer:"
        )
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return str(resp.json().get("response", "")).strip()
