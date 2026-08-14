from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.budget import Budget
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction
from finance.schemas.budget import BudgetCreate, BudgetUpdate


async def list_budgets(session: AsyncSession) -> list[Budget]:
    result = await session.execute(
        select(Budget).order_by(Budget.category_id)
    )
    return list(result.scalars().all())


async def get_budget(session: AsyncSession, budget_id: int) -> Budget:
    budget = await session.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


async def create_budget(session: AsyncSession, data: BudgetCreate) -> Budget:
    cat = await session.get(Category, data.category_id)
    if cat is None:
        raise HTTPException(status_code=400, detail="Category not found")
    if data.period not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="Period must be 'monthly' or 'weekly'")

    budget = Budget(**data.model_dump())
    session.add(budget)
    await session.commit()
    await session.refresh(budget)
    return budget


async def update_budget(
    session: AsyncSession, budget_id: int, data: BudgetUpdate
) -> Budget:
    budget = await get_budget(session, budget_id)
    updates = data.model_dump(exclude_unset=True)

    if "category_id" in updates:
        cat = await session.get(Category, updates["category_id"])
        if cat is None:
            raise HTTPException(status_code=400, detail="Category not found")

    if "period" in updates and updates["period"] not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="Period must be 'monthly' or 'weekly'")

    for key, value in updates.items():
        setattr(budget, key, value)

    await session.commit()
    await session.refresh(budget)
    return budget


async def delete_budget(session: AsyncSession, budget_id: int) -> None:
    budget = await get_budget(session, budget_id)
    await session.delete(budget)
    await session.commit()


async def get_budget_status(
    session: AsyncSession, period_start: date, period_end: date
) -> list[dict]:
    budgets = await session.execute(
        select(Budget).where(
            Budget.start_date <= period_end,
            (Budget.end_date.is_(None)) | (Budget.end_date >= period_start),
        )
    )
    active_budgets = list(budgets.scalars().all())

    if not active_budgets:
        return []

    category_ids = [b.category_id for b in active_budgets]

    spending_result = await session.execute(
        select(
            LineItem.category_id,
            func.coalesce(func.sum(LineItem.amount_cents), 0).label("spent"),
        )
        .join(Transaction, LineItem.transaction_id == Transaction.id)
        .where(
            LineItem.category_id.in_(category_ids),
            Transaction.posted_at >= period_start,
            Transaction.posted_at <= period_end,
        )
        .group_by(LineItem.category_id)
    )
    spent_map: dict[int, int] = {
        row.category_id: row.spent for row in spending_result
    }

    today = date.today()
    days_remaining = max(0, (period_end - today).days + 1)

    results = []
    for b in active_budgets:
        spent = spent_map.get(b.category_id, 0)
        remaining = b.amount_cents - spent
        percent = (spent / b.amount_cents * 100) if b.amount_cents > 0 else 0.0
        percent_remaining = (
            (remaining / b.amount_cents * 100) if b.amount_cents > 0 else 0.0
        )
        results.append(
            {
                "budget_id": b.id,
                "category_id": b.category_id,
                "category_name": b.category.name if b.category else "",
                "category_icon": b.category.icon if b.category else None,
                "category_color": b.category.color if b.category else None,
                "budgeted_cents": b.amount_cents,
                "spent_cents": spent,
                "remaining_cents": remaining,
                "percent_used": round(percent, 1),
                "percent_remaining": round(percent_remaining, 1),
                "is_pinned": bool(b.is_pinned),
                "period": b.period,
                "period_start": period_start,
                "period_end": period_end,
                "days_remaining": days_remaining,
            }
        )

    return results


async def get_spending_suggestions(
    session: AsyncSession, months: int = 3
) -> list[dict]:
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    end = today.replace(day=1) - timedelta(days=1)

    income_ids = await _income_category_ids(session)

    result = await session.execute(
        select(
            LineItem.category_id,
            func.coalesce(func.sum(LineItem.amount_cents), 0).label("total"),
            func.count(LineItem.id).label("txn_count"),
        )
        .join(Transaction, LineItem.transaction_id == Transaction.id)
        .where(
            Transaction.posted_at >= start,
            Transaction.posted_at <= end,
        )
        .group_by(LineItem.category_id)
    )

    suggestions = []
    for row in result:
        cat = await session.get(Category, row.category_id)
        if cat is None:
            continue
        is_income = row.category_id in income_ids
        avg = abs(row.total) // months
        rounded = ((avg + 499) // 500) * 500
        if rounded < 500:
            rounded = 500
        suggestions.append({
            "category_id": row.category_id,
            "category_name": cat.name,
            "avg_monthly_cents": avg,
            "suggested_cents": rounded,
            "total_cents": row.total,
            "months": months,
            "txn_count": row.txn_count,
            "is_income": is_income,
        })

    suggestions.sort(key=lambda s: s["avg_monthly_cents"], reverse=True)
    return suggestions


async def _income_category_ids(session: AsyncSession) -> set[int]:
    result = await session.execute(
        select(Category.id).where(Category.is_income.is_(True))
    )
    return {row[0] for row in result}


async def get_income_summary(
    session: AsyncSession, period_start: date, period_end: date
) -> dict:
    income_ids = await _income_category_ids(session)
    if not income_ids:
        return {"total_cents": 0, "categories": []}

    result = await session.execute(
        select(
            LineItem.category_id,
            func.coalesce(func.sum(LineItem.amount_cents), 0).label("total"),
            func.count(LineItem.id).label("txn_count"),
        )
        .join(Transaction, LineItem.transaction_id == Transaction.id)
        .where(
            LineItem.category_id.in_(income_ids),
            Transaction.posted_at >= period_start,
            Transaction.posted_at <= period_end,
        )
        .group_by(LineItem.category_id)
    )

    categories = []
    total = 0
    for row in result:
        cat = await session.get(Category, row.category_id)
        if cat is None:
            continue
        categories.append({
            "category_id": row.category_id,
            "category_name": cat.name,
            "category_icon": cat.icon,
            "category_color": cat.color,
            "amount_cents": abs(row.total),
            "txn_count": row.txn_count,
        })
        total += abs(row.total)

    categories.sort(key=lambda c: c["amount_cents"], reverse=True)
    return {"total_cents": total, "categories": categories}
