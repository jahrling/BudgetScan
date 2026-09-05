from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.budget import Budget
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction
from finance.schemas.budget import BudgetCreate, BudgetUpdate
from finance.services.period_utils import parse_month_param, prev_month_str


async def list_budgets(
    session: AsyncSession, month: str | None = None
) -> list[Budget]:
    stmt = select(Budget).order_by(Budget.category_id)
    if month is not None:
        stmt = stmt.where(Budget.year_month == month)
    result = await session.execute(stmt)
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

    dump = data.model_dump()
    if dump.get("start_date") is None:
        start, _ = parse_month_param(data.year_month)
        dump["start_date"] = start

    budget = Budget(**dump)
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


async def _build_children_map(session: AsyncSession) -> dict[int, list[int]]:
    result = await session.execute(select(Category.id, Category.parent_id))
    children_map: dict[int, list[int]] = {}
    for cat_id, parent_id in result:
        if parent_id is not None:
            children_map.setdefault(parent_id, []).append(cat_id)
    return children_map


def _collect_effective_ids(
    cat_id: int,
    children_map: dict[int, list[int]],
    budgeted_ids: set[int],
    is_root: bool = True,
) -> set[int]:
    """Walk from cat_id collecting it and descendants, stopping at any
    descendant that has its own budget (that subtree belongs to the
    child budget instead)."""
    result = set()
    if is_root or cat_id not in budgeted_ids:
        result.add(cat_id)
        for child_id in children_map.get(cat_id, []):
            result |= _collect_effective_ids(
                child_id, children_map, budgeted_ids, is_root=False
            )
    return result


async def get_budget_status(
    session: AsyncSession,
    period_start: date,
    period_end: date,
    year_month: str,
) -> list[dict]:
    budgets_result = await session.execute(
        select(Budget).where(Budget.year_month == year_month)
    )
    active_budgets = list(budgets_result.scalars().all())

    if not active_budgets:
        return []

    budgeted_ids = {b.category_id for b in active_budgets}
    children_map = await _build_children_map(session)

    effective_per_budget: dict[int, set[int]] = {}
    all_effective_ids: set[int] = set()
    for b in active_budgets:
        effective = _collect_effective_ids(
            b.category_id, children_map, budgeted_ids
        )
        effective_per_budget[b.category_id] = effective
        all_effective_ids |= effective

    spending_result = await session.execute(
        select(
            LineItem.category_id,
            func.coalesce(func.sum(LineItem.amount_cents), 0).label("spent"),
        )
        .join(Transaction, LineItem.transaction_id == Transaction.id)
        .where(
            LineItem.category_id.in_(all_effective_ids),
            Transaction.posted_at >= period_start,
            Transaction.posted_at <= period_end,
            Transaction.excluded.is_(None),
        )
        .group_by(LineItem.category_id)
    )
    per_category_spent: dict[int, int] = {
        row.category_id: row.spent for row in spending_result
    }

    today = date.today()
    days_remaining = max(0, (period_end - today).days + 1)

    results = []
    for b in active_budgets:
        effective = effective_per_budget[b.category_id]
        raw_spent = sum(per_category_spent.get(cid, 0) for cid in effective)
        is_income = b.category.is_income if b.category else False
        spent = raw_spent if is_income else -raw_spent
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
            Transaction.excluded.is_(None),
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
            Transaction.excluded.is_(None),
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


async def get_unbudgeted_spend(
    session: AsyncSession,
    period_start: date,
    period_end: date,
    year_month: str,
) -> dict:
    budgeted_ids_result = await session.execute(
        select(Budget.category_id).where(Budget.year_month == year_month)
    )
    budgeted_ids = {row[0] for row in budgeted_ids_result}
    children_map = await _build_children_map(session)
    covered_ids: set[int] = set()
    for bid in budgeted_ids:
        covered_ids |= _collect_effective_ids(bid, children_map, budgeted_ids)
    income_ids = await _income_category_ids(session)
    excluded_ids = covered_ids | income_ids

    items: list[dict] = []
    grand_total = 0

    if excluded_ids:
        line_result = await session.execute(
            select(
                LineItem.category_id,
                func.coalesce(func.sum(LineItem.amount_cents), 0).label("spent"),
                func.count(LineItem.id).label("cnt"),
            )
            .join(Transaction, LineItem.transaction_id == Transaction.id)
            .where(
                LineItem.category_id.not_in(excluded_ids),
                Transaction.posted_at >= period_start,
                Transaction.posted_at <= period_end,
                Transaction.excluded.is_(None),
            )
            .group_by(LineItem.category_id)
        )
    else:
        line_result = await session.execute(
            select(
                LineItem.category_id,
                func.coalesce(func.sum(LineItem.amount_cents), 0).label("spent"),
                func.count(LineItem.id).label("cnt"),
            )
            .join(Transaction, LineItem.transaction_id == Transaction.id)
            .where(
                Transaction.posted_at >= period_start,
                Transaction.posted_at <= period_end,
                Transaction.excluded.is_(None),
            )
            .group_by(LineItem.category_id)
        )

    for row in line_result:
        cat = await session.get(Category, row.category_id)
        if cat is None:
            continue
        if cat.is_income:
            continue
        spent = -row.spent  # negate expenses to positive
        if spent <= 0:
            continue
        items.append({
            "category_id": row.category_id,
            "category_name": cat.name,
            "spent_cents": spent,
            "txn_count": row.cnt,
        })
        grand_total += spent

    # Transactions with no line items at all (truly uncategorized)
    from sqlalchemy import exists as sa_exists
    no_li_result = await session.execute(
        select(
            func.coalesce(func.sum(Transaction.amount_cents), 0).label("spent"),
            func.count(Transaction.id).label("cnt"),
        )
        .where(
            Transaction.posted_at >= period_start,
            Transaction.posted_at <= period_end,
            Transaction.excluded.is_(None),
            ~sa_exists(
                select(LineItem.id).where(LineItem.transaction_id == Transaction.id)
            ),
            Transaction.amount_cents < 0,
        )
    )
    row = no_li_result.one()
    if row.cnt > 0:
        spent = -row.spent
        items.append({
            "category_id": None,
            "category_name": "Uncategorized",
            "spent_cents": spent,
            "txn_count": row.cnt,
        })
        grand_total += spent

    items.sort(key=lambda i: i["spent_cents"], reverse=True)
    return {"total_cents": grand_total, "items": items}


async def get_month_comparison(
    session: AsyncSession,
    current_ym: str,
    prior_ym: str,
    current_start: date,
    current_end: date,
    prior_start: date,
    prior_end: date,
) -> dict:
    cur_budgets = await session.execute(
        select(Budget).where(Budget.year_month == current_ym)
    )
    cur_budgets = list(cur_budgets.scalars().all())

    pri_budgets = await session.execute(
        select(Budget).where(Budget.year_month == prior_ym)
    )
    pri_budgets = list(pri_budgets.scalars().all())

    all_cat_ids = {b.category_id for b in cur_budgets} | {b.category_id for b in pri_budgets}
    if not all_cat_ids:
        return {"current_month": current_ym, "prior_month": prior_ym, "items": []}

    cur_budget_map = {b.category_id: b for b in cur_budgets}
    pri_budget_map = {b.category_id: b for b in pri_budgets}

    children_map = await _build_children_map(session)
    cur_budgeted_ids = {b.category_id for b in cur_budgets}
    pri_budgeted_ids = {b.category_id for b in pri_budgets}

    cur_effective: dict[int, set[int]] = {}
    pri_effective: dict[int, set[int]] = {}
    all_effective_ids: set[int] = set()
    for cid in all_cat_ids:
        if cid in cur_budgeted_ids:
            eff = _collect_effective_ids(cid, children_map, cur_budgeted_ids)
            cur_effective[cid] = eff
            all_effective_ids |= eff
        if cid in pri_budgeted_ids:
            eff = _collect_effective_ids(cid, children_map, pri_budgeted_ids)
            pri_effective[cid] = eff
            all_effective_ids |= eff

    async def per_cat_spending(cat_ids: set[int], start: date, end: date) -> dict[int, int]:
        if not cat_ids:
            return {}
        result = await session.execute(
            select(
                LineItem.category_id,
                func.coalesce(func.sum(LineItem.amount_cents), 0).label("spent"),
            )
            .join(Transaction, LineItem.transaction_id == Transaction.id)
            .where(
                LineItem.category_id.in_(cat_ids),
                Transaction.posted_at >= start,
                Transaction.posted_at <= end,
                Transaction.excluded.is_(None),
            )
            .group_by(LineItem.category_id)
        )
        return {row.category_id: row.spent for row in result}

    cur_per_cat = await per_cat_spending(all_effective_ids, current_start, current_end)
    pri_per_cat = await per_cat_spending(all_effective_ids, prior_start, prior_end)

    items = []
    for cid in sorted(all_cat_ids):
        cat = await session.get(Category, cid)
        if cat is None:
            continue
        is_income = cat.is_income

        cur_eff = cur_effective.get(cid, {cid})
        pri_eff = pri_effective.get(cid, {cid})
        raw_cur = sum(cur_per_cat.get(c, 0) for c in cur_eff)
        raw_pri = sum(pri_per_cat.get(c, 0) for c in pri_eff)
        cur_s = raw_cur if is_income else -raw_cur
        pri_s = raw_pri if is_income else -raw_pri

        items.append({
            "category_id": cid,
            "category_name": cat.name,
            "category_icon": cat.icon,
            "category_color": cat.color,
            "current_budgeted_cents": cur_budget_map[cid].amount_cents if cid in cur_budget_map else 0,
            "current_spent_cents": cur_s,
            "prior_spent_cents": pri_s,
            "prior_budgeted_cents": pri_budget_map[cid].amount_cents if cid in pri_budget_map else 0,
        })

    return {"current_month": current_ym, "prior_month": prior_ym, "items": items}


async def seed_month(
    session: AsyncSession, target_month: str, *, replace: bool = False
) -> list[Budget]:
    existing = await session.execute(
        select(Budget).where(Budget.year_month == target_month)
    )
    existing_list = list(existing.scalars().all())
    if existing_list:
        if not replace:
            raise HTTPException(
                status_code=409,
                detail=f"Budgets already exist for {target_month}",
            )
        for b in existing_list:
            await session.delete(b)
        await session.flush()

    source_result = await session.execute(
        select(Budget.year_month)
        .where(Budget.year_month < target_month)
        .distinct()
        .order_by(Budget.year_month.desc())
        .limit(1)
    )
    source_month = source_result.scalar_one_or_none()
    if source_month is None:
        raise HTTPException(
            status_code=404,
            detail="No prior month budgets to copy from",
        )

    source_budgets = await session.execute(
        select(Budget).where(Budget.year_month == source_month)
    )

    target_start, _ = parse_month_param(target_month)
    new_budgets = []
    for b in source_budgets.scalars().all():
        new_b = Budget(
            category_id=b.category_id,
            period=b.period,
            amount_cents=b.amount_cents,
            start_date=target_start,
            end_date=None,
            is_pinned=b.is_pinned,
            year_month=target_month,
        )
        session.add(new_b)
        new_budgets.append(new_b)

    await session.commit()
    for b in new_budgets:
        await session.refresh(b)
    return new_budgets
