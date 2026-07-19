"""Query routing: the explicit boundary between SQL and vector retrieval.

ADR 0003 mandates that numeric/aggregation questions are answered by SQL against
SQLite, and only free-text/semantic questions touch the vector index. This
module is the single, deterministic, testable place that decision is made.

`classify_intent` is a pure function — no I/O, no model call — so the routing
boundary is fully unit-testable and a numeric query can be proven to never reach
vector retrieval. It is intentionally conservative: anything that smells numeric
routes to SQL. Vector retrieval is the fallback for genuinely free-text intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    SQL = "sql"
    VECTOR = "vector"


@dataclass(frozen=True)
class Intent:
    route: Route
    reason: str


# Words/patterns that signal a numeric or aggregation question. Any hit forces
# the SQL path.
_NUMERIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bhow much\b",
        r"\bhow many\b",
        r"\btotal(s|ed|ling)?\b",
        r"\bsum\b",
        r"\baverage\b",
        r"\bavg\b",
        r"\bmean\b",
        r"\bspend(ing|s|t)?\b",
        r"\bspent\b",
        r"\bcost(s|ing)?\b",
        r"\bbudget(s|ed)?\b",
        r"\bbalance\b",
        r"\bremaining\b",
        r"\bleft (in|for|over)\b",
        r"\bover budget\b",
        r"\bunder budget\b",
        r"\bcount\b",
        r"\bmore than\b",
        r"\bless than\b",
        r"\bcompare(d)?\b",
        r"\$\s?\d",  # a dollar figure
        r"\b\d+\s?(dollars|bucks|cents)\b",
        r"\bper (month|week|day|year)\b",
    )
)

# Words that signal a free-text/"why" question. These only matter when NO
# numeric pattern fired — numeric always wins.
_SEMANTIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwhy\b",
        r"\bwhat (was|were) .* for\b",
        r"\breason\b",
        r"\bnote(s)?\b",
        r"\bremind me\b",
        r"\bwhat did i (buy|get|purchase)\b",
        r"\bdescribe\b",
        r"\bwhat is this\b",
        r"\bwhat's this\b",
    )
)


def classify_intent(query: str) -> Intent:
    """Classify a natural-language finance question into a retrieval route.

    Numeric/aggregation intent -> SQL. Everything else -> vector retrieval over
    prose. Numeric signals take strict priority: if a query contains both a
    dollar figure and the word "why", it still routes to SQL, because any answer
    that involves a number must come from the structured store.
    """
    text = (query or "").strip()
    if not text:
        return Intent(Route.VECTOR, "empty query; nothing numeric to compute")

    for pat in _NUMERIC_PATTERNS:
        if pat.search(text):
            return Intent(Route.SQL, f"matched numeric signal: {pat.pattern!r}")

    for pat in _SEMANTIC_PATTERNS:
        if pat.search(text):
            return Intent(Route.VECTOR, f"matched semantic signal: {pat.pattern!r}")

    # No explicit signal. Default to vector: SQL aggregation needs a numeric
    # intent to compute anything, so an ambiguous free-text question is better
    # served by prose retrieval than by an empty aggregate.
    return Intent(Route.VECTOR, "no numeric signal; defaulting to prose retrieval")


def is_numeric_query(query: str) -> bool:
    return classify_intent(query).route is Route.SQL
