from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.schemas.budget import (
    BudgetCreate,
    BudgetRead,
    BudgetStatusItem,
    BudgetUpdate,
    IncomeSummary,
    MonthComparison,
    UnbudgetedSpend,
)
from finance.services import budget as budget_service
from finance.services.period_utils import parse_month_param, prev_month_str

router = APIRouter(
    prefix="/api/budgets",
    tags=["budgets"],
    dependencies=[Depends(current_user)],
)


@router.get("", response_model=list[BudgetRead])
async def list_budgets(
    month: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await budget_service.list_budgets(session, month=month)


@router.get("/status", response_model=list[BudgetStatusItem])
async def budget_status(
    month: str = Query("current"),
    session: AsyncSession = Depends(get_session),
):
    start, end = parse_month_param(month)
    ym = month if month != "current" else f"{start.year}-{start.month:02d}"
    return await budget_service.get_budget_status(session, start, end, ym)


@router.get("/suggestions")
async def spending_suggestions(
    months: int = Query(3, ge=1, le=12),
    session: AsyncSession = Depends(get_session),
):
    return await budget_service.get_spending_suggestions(session, months)


@router.get("/income-summary", response_model=IncomeSummary)
async def income_summary(
    month: str = Query("current"),
    session: AsyncSession = Depends(get_session),
):
    start, end = parse_month_param(month)
    return await budget_service.get_income_summary(session, start, end)


@router.get("/unbudgeted-spend", response_model=UnbudgetedSpend)
async def unbudgeted_spend(
    month: str = Query("current"),
    session: AsyncSession = Depends(get_session),
):
    start, end = parse_month_param(month)
    ym = month if month != "current" else f"{start.year}-{start.month:02d}"
    return await budget_service.get_unbudgeted_spend(session, start, end, ym)


@router.get("/comparison", response_model=MonthComparison)
async def month_comparison(
    month: str = Query("current"),
    session: AsyncSession = Depends(get_session),
):
    cur_start, cur_end = parse_month_param(month)
    cur_ym = month if month != "current" else f"{cur_start.year}-{cur_start.month:02d}"
    pri_ym = prev_month_str(cur_ym)
    pri_start, pri_end = parse_month_param(pri_ym)
    return await budget_service.get_month_comparison(
        session, cur_ym, pri_ym, cur_start, cur_end, pri_start, pri_end
    )


@router.post("/seed", response_model=list[BudgetRead])
async def seed_month(
    month: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    return await budget_service.seed_month(session, month)


@router.get("/{budget_id}", response_model=BudgetRead)
async def get_budget(
    budget_id: int, session: AsyncSession = Depends(get_session)
):
    return await budget_service.get_budget(session, budget_id)


@router.post("", response_model=BudgetRead, status_code=201)
async def create_budget(
    data: BudgetCreate, session: AsyncSession = Depends(get_session)
):
    return await budget_service.create_budget(session, data)


@router.patch("/{budget_id}", response_model=BudgetRead)
async def update_budget(
    budget_id: int,
    data: BudgetUpdate,
    session: AsyncSession = Depends(get_session),
):
    return await budget_service.update_budget(session, budget_id, data)


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: int, session: AsyncSession = Depends(get_session)
):
    await budget_service.delete_budget(session, budget_id)
