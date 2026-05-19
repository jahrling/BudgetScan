from datetime import date

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

    results = []
    for b in active_budgets:
        spent = spent_map.get(b.category_id, 0)
        remaining = b.amount_cents - spent
        percent = (spent / b.amount_cents * 100) if b.amount_cents > 0 else 0.0
        results.append(
            {
                "category_id": b.category_id,
                "category_name": b.category.name if b.category else "",
                "budgeted_cents": b.amount_cents,
                "spent_cents": spent,
                "remaining_cents": remaining,
                "percent_used": round(percent, 1),
            }
        )

    return results
