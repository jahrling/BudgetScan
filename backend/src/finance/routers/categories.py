# TODO: Add auth dependency once session auth is implemented (phase 3).

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from finance.db import get_session
from finance.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from finance.services import category as category_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
async def list_categories(session: AsyncSession = Depends(get_session)):
    return await category_service.list_categories(session)


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: int, session: AsyncSession = Depends(get_session)
):
    return await category_service.get_category(session, category_id)


@router.post("", response_model=CategoryRead, status_code=201)
async def create_category(
    data: CategoryCreate, session: AsyncSession = Depends(get_session)
):
    return await category_service.create_category(session, data)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    session: AsyncSession = Depends(get_session),
):
    return await category_service.update_category(session, category_id, data)


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: int, session: AsyncSession = Depends(get_session)
):
    await category_service.delete_category(session, category_id)
