"""SQL aggregations return exact, cents-precise numbers from the structured store."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from finance.services import aggregation
from finance.tests.rag_stubs import (
    add_transaction,
    seed_account,
    seed_category,
)


async def _seed(session: AsyncSession):
    acct = await seed_account(session)
    food = await seed_category(session, "Food")
    groceries = await seed_category(session, "Groceries", parent_id=food.id)
    dining = await seed_category(session, "Dining", parent_id=food.id)
    household = await seed_category(session, "Household")

    # Groceries: 4500 + 1200 + 800 = 6500
    await add_transaction(session, account_id=acct.id, items=[(groceries.id, 4500)])
    await add_transaction(
        session, account_id=acct.id, items=[(groceries.id, 1200), (groceries.id, 800)]
    )
    # Dining: 2000
    await add_transaction(session, account_id=acct.id, items=[(dining.id, 2000)])
    # Household: 3300
    await add_transaction(session, account_id=acct.id, items=[(household.id, 3300)])
    return acct, food, groceries, dining, household


async def test_spend_for_leaf_category_exact(session: AsyncSession) -> None:
    await _seed(session)
    cents = await aggregation.spend_for_category_name(session, "Groceries")
    assert cents == 6500


async def test_spend_for_parent_includes_descendants(session: AsyncSession) -> None:
    await _seed(session)
    # Food = Groceries (6500) + Dining (2000) = 8500
    cents = await aggregation.spend_for_category_name(session, "Food")
    assert cents == 8500


async def test_total_spend_all(session: AsyncSession) -> None:
    await _seed(session)
    # 6500 + 2000 + 3300 = 11800
    cents = await aggregation.total_spend(session)
    assert cents == 11800


async def test_unknown_category_is_zero(session: AsyncSession) -> None:
    await _seed(session)
    assert await aggregation.spend_for_category_name(session, "Yachts") == 0


async def test_date_filter(session: AsyncSession) -> None:
    acct = await seed_account(session)
    cat = await seed_category(session, "Gas")
    await add_transaction(
        session,
        account_id=acct.id,
        items=[(cat.id, 5000)],
        posted_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    await add_transaction(
        session,
        account_id=acct.id,
        items=[(cat.id, 7000)],
        posted_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
    )
    q1 = await aggregation.total_spend(
        session,
        date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2026, 3, 31, tzinfo=timezone.utc),
    )
    assert q1 == 5000


async def test_breakdown_sorted_desc(session: AsyncSession) -> None:
    await _seed(session)
    rows = await aggregation.spend_by_category(session)
    totals = {r.category_name: r.total_cents for r in rows}
    assert totals["Groceries"] == 6500
    assert totals["Household"] == 3300
    assert totals["Dining"] == 2000
    # Sorted highest-first.
    assert [r.total_cents for r in rows] == sorted(
        (r.total_cents for r in rows), reverse=True
    )
