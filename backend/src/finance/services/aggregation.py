"""Exact spend aggregations over the structured store (SQLite).

This is the SQL side of ADR 0003: every numeric answer is computed here, in
integer cents, straight from `line_items` joined to `transactions`. Line items
of a transaction sum to that transaction's amount, so summing line items is
equivalent to summing transaction totals — and it lets us slice by category.

Nothing in this module reads annotations or embeddings. Numbers come only from
the structured store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction


@dataclass
class CategorySpend:
    category_id: int
    category_name: str
    total_cents: int


async def resolve_category_ids(session: AsyncSession, name: str) -> list[int]:
    """Return the id of the category matching `name` plus all its descendants.

    Category names are hierarchical (Food > Groceries), so asking about "Food"
    should include everything beneath it. Matching is case-insensitive and
    exact on the name. Returns [] if no category matches.
    """
    rows = await session.execute(select(Category))
    cats = list(rows.scalars().all())
    by_parent: dict[int | None, list[Category]] = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)

    matched = [c for c in cats if c.name.strip().lower() == name.strip().lower()]
    if not matched:
        return []

    ids: list[int] = []
    stack = list(matched)
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if cur.id in seen:
            continue
        seen.add(cur.id)
        ids.append(cur.id)
        stack.extend(by_parent.get(cur.id, []))
    return ids


def _apply_date_filter(
    stmt: Select[Any],
    *,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[Any]:
    if date_from is not None:
        stmt = stmt.where(Transaction.posted_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.posted_at <= date_to)
    return stmt


async def total_spend(
    session: AsyncSession,
    *,
    category_ids: list[int] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    """Total spend in integer cents, optionally filtered by category and date."""
    stmt = (
        select(func.coalesce(func.sum(LineItem.amount_cents), 0))
        .select_from(LineItem)
        .join(Transaction, Transaction.id == LineItem.transaction_id)
    )
    if category_ids is not None:
        if not category_ids:
            return 0
        stmt = stmt.where(LineItem.category_id.in_(category_ids))
    stmt = _apply_date_filter(stmt, date_from=date_from, date_to=date_to)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def spend_for_category_name(
    session: AsyncSession,
    name: str,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    """Total spend in cents for a named category (including its descendants)."""
    ids = await resolve_category_ids(session, name)
    return await total_spend(
        session, category_ids=ids, date_from=date_from, date_to=date_to
    )


async def spend_by_category(
    session: AsyncSession,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[CategorySpend]:
    """Per-category spend breakdown, in cents, highest first."""
    stmt = (
        select(
            Category.id,
            Category.name,
            func.coalesce(func.sum(LineItem.amount_cents), 0),
        )
        .select_from(LineItem)
        .join(Transaction, Transaction.id == LineItem.transaction_id)
        .join(Category, Category.id == LineItem.category_id)
        .group_by(Category.id, Category.name)
    )
    stmt = _apply_date_filter(stmt, date_from=date_from, date_to=date_to)
    rows = await session.execute(stmt)
    out = [
        CategorySpend(category_id=cid, category_name=cname, total_cents=int(total))
        for cid, cname, total in rows.all()
    ]
    out.sort(key=lambda cs: cs.total_cents, reverse=True)
    return out
