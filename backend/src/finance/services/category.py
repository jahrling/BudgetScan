from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.category import Category
from finance.schemas.category import CategoryCreate, CategoryUpdate


async def _check_parent_exists(session: AsyncSession, parent_id: int) -> None:
    parent = await session.get(Category, parent_id)
    if parent is None:
        raise HTTPException(status_code=400, detail="Parent category not found")


async def _would_create_cycle(
    session: AsyncSession, category_id: int, new_parent_id: int
) -> bool:
    visited: set[int] = set()
    current_id: int | None = new_parent_id
    while current_id is not None:
        if current_id == category_id:
            return True
        if current_id in visited:
            return True
        visited.add(current_id)
        ancestor = await session.get(Category, current_id)
        current_id = ancestor.parent_id if ancestor else None
    return False


async def list_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def get_category(session: AsyncSession, category_id: int) -> Category:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return cat


async def create_category(session: AsyncSession, data: CategoryCreate) -> Category:
    if data.parent_id is not None:
        await _check_parent_exists(session, data.parent_id)

    cat = Category(**data.model_dump(), source="app")
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


async def update_category(
    session: AsyncSession, category_id: int, data: CategoryUpdate
) -> Category:
    cat = await get_category(session, category_id)
    updates = data.model_dump(exclude_unset=True)

    new_parent_id = updates.get("parent_id")
    if new_parent_id is not None:
        if new_parent_id == category_id:
            raise HTTPException(status_code=400, detail="Category cannot be its own parent")
        await _check_parent_exists(session, new_parent_id)
        if await _would_create_cycle(session, category_id, new_parent_id):
            raise HTTPException(status_code=400, detail="This parent would create a cycle")

    for key, value in updates.items():
        setattr(cat, key, value)

    await session.commit()
    await session.refresh(cat)
    return cat


async def delete_category(session: AsyncSession, category_id: int) -> None:
    cat = await get_category(session, category_id)
    await session.delete(cat)
    await session.commit()
