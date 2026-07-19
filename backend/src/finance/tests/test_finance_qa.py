"""End-to-end routing behaviour of the summarization/RAG layer (ADR 0003).

The three scenarios the layer must guarantee:
  (a) an aggregation query returns exact SQL-derived numbers,
  (b) a "why did I buy X" query retrieves the right note,
  (c) a numeric query never routes to vector retrieval.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from finance.services import finance_qa, vector_store
from finance.services.query_router import Route
from finance.tests.rag_stubs import (
    StubEmbedder,
    StubGenerator,
    SpyStore,
    add_annotation,
    add_transaction,
    seed_account,
    seed_category,
)


# --- (a) aggregation query returns exact SQL-derived numbers ----------------

async def test_aggregation_query_returns_exact_sql_number(session: AsyncSession) -> None:
    acct = await seed_account(session)
    groceries = await seed_category(session, "Groceries")
    await add_transaction(session, account_id=acct.id, items=[(groceries.id, 4500)])
    await add_transaction(session, account_id=acct.id, items=[(groceries.id, 2075)])

    result = await finance_qa.answer(session, "How much did I spend on groceries?")

    assert result.route is Route.SQL
    assert result.data["amount_cents"] == 6575  # exact, from SQL
    assert result.data["category"] == "Groceries"
    assert "$65.75" in result.text
    assert result.sources == []  # numeric answers cite no prose


# --- (b) "why did I buy X" retrieves the right note -------------------------

async def test_why_query_retrieves_right_note(session: AsyncSession) -> None:
    acct = await seed_account(session)
    misc = await seed_category(session, "Household")
    txn = await add_transaction(session, account_id=acct.id, items=[(misc.id, 18999)])

    target = await add_annotation(
        session,
        "Bought a dehumidifier because the basement kept flooding after heavy rain.",
        transaction_id=txn.id,
    )
    await add_annotation(
        session, "Signed up for the annual gym membership to train for the marathon."
    )
    await add_annotation(
        session, "Replacement air filter for the furnace, overdue for a year."
    )

    embedder = StubEmbedder()
    store = await vector_store.rebuild_from_db(session, embedder, persist=False)
    generator = StubGenerator()

    result = await finance_qa.answer(
        session,
        "Why did I buy the dehumidifier?",
        embedder=embedder,
        store=store,
        generator=generator,
    )

    assert result.route is Route.VECTOR
    assert result.sources, "expected at least one retrieved note"
    top = result.sources[0]
    assert top.source == "annotation"
    assert top.ref_id == target.id
    assert "dehumidifier" in top.text.lower()
    # The generator answered from the retrieved note, not from thin air.
    assert "dehumidifier" in result.text.lower()


# --- (c) a numeric query never routes to vector retrieval -------------------

async def test_numeric_query_never_touches_vector(session: AsyncSession) -> None:
    acct = await seed_account(session)
    groceries = await seed_category(session, "Groceries")
    await add_transaction(session, account_id=acct.id, items=[(groceries.id, 1000)])
    await add_annotation(session, "why did I buy so many groceries this week")

    embedder = StubEmbedder()
    spy_store = SpyStore()

    result = await finance_qa.answer(
        session,
        "How much did I spend on groceries?",
        embedder=embedder,
        store=spy_store,
    )

    assert result.route is Route.SQL
    assert embedder.calls == 0, "numeric query must not embed anything"
    assert spy_store.searched is False, "numeric query must not hit the vector index"


async def test_semantic_query_does_touch_vector_positive_control(
    session: AsyncSession,
) -> None:
    # Mirror of the above: a genuine free-text query DOES use the vector path,
    # proving the assertion in the numeric test is meaningful.
    await seed_account(session)
    await add_annotation(session, "picked up the framed photo for the hallway")

    embedder = StubEmbedder()
    spy = SpyStore()  # empty index is fine; we only assert it was consulted

    result = await finance_qa.answer(
        session,
        "why did I go to the hallway store",
        embedder=embedder,
        store=spy,
        generator=StubGenerator(),
    )

    assert result.route is Route.VECTOR
    assert embedder.calls >= 1
    assert spy.searched is True
