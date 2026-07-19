"""The SQL-vs-vector routing boundary (ADR 0003) is deterministic and testable."""

import pytest

from finance.services.query_router import Route, classify_intent, is_numeric_query

NUMERIC_QUERIES = [
    "How much did I spend on groceries in Q2?",
    "What's my total dining spend this year?",
    "how many transactions were over $50",
    "What is the average grocery bill?",
    "sum of household costs",
    "How much is left in my entertainment budget?",
    "Did I spend more than $200 on gas?",
    "compare grocery spend to last month",
    "what did coffee cost me per month",
    "How much have I spent?",
]

SEMANTIC_QUERIES = [
    "Why did I buy the dehumidifier?",
    "What was that Target run for?",
    "remind me why I got the annual membership",
    "what did I buy at the hardware store",
    "describe the receipt from Costco",
    "what is this charge",
]


@pytest.mark.parametrize("query", NUMERIC_QUERIES)
def test_numeric_queries_route_to_sql(query: str) -> None:
    intent = classify_intent(query)
    assert intent.route is Route.SQL, f"{query!r} -> {intent.reason}"
    assert is_numeric_query(query) is True


@pytest.mark.parametrize("query", SEMANTIC_QUERIES)
def test_semantic_queries_route_to_vector(query: str) -> None:
    intent = classify_intent(query)
    assert intent.route is Route.VECTOR, f"{query!r} -> {intent.reason}"
    assert is_numeric_query(query) is False


def test_numeric_signal_wins_over_semantic() -> None:
    # Contains both "why" (semantic) and a dollar figure (numeric). Any answer
    # touching a number must come from SQL, so numeric must win.
    intent = classify_intent("why did I spend $300 on furniture")
    assert intent.route is Route.SQL


def test_empty_query_defaults_to_vector() -> None:
    assert classify_intent("").route is Route.VECTOR
    assert classify_intent("   ").route is Route.VECTOR
