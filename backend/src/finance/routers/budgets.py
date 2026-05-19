from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from finance.db import get_session
from finance.schemas.budget import (
    BudgetCreate,
    BudgetRead,
    BudgetStatusItem,
    BudgetUpdate,
)
from finance.services import budget as budget_service

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetRead])
async def list_budgets(session: AsyncSession = Depends(get_session)):
    return await budget_service.list_budgets(session)


@router.get("/status", response_model=list[BudgetStatusItem])
async def budget_status(
    period: str = Query("current_month"),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    if period == "current_month":
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    elif period == "current_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    else:
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

    return await budget_service.get_budget_status(session, start, end)


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
