import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from finance.schemas.category import CategoryCreate, CategoryUpdate
from finance.services.category import (
    create_category,
    delete_category,
    get_category,
    list_categories,
    update_category,
)


async def test_create_root_category(session: AsyncSession) -> None:
    cat = await create_category(session, CategoryCreate(name="Food"))
    assert cat.id is not None
    assert cat.name == "Food"
    assert cat.parent_id is None


async def test_create_child_category(session: AsyncSession) -> None:
    parent = await create_category(session, CategoryCreate(name="Food"))
    child = await create_category(
        session, CategoryCreate(name="Groceries", parent_id=parent.id)
    )
    assert child.parent_id == parent.id


async def test_create_with_invalid_parent(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await create_category(session, CategoryCreate(name="Bad", parent_id=9999))
    assert exc.value.status_code == 400


async def test_list_categories(session: AsyncSession) -> None:
    await create_category(session, CategoryCreate(name="B"))
    await create_category(session, CategoryCreate(name="A"))
    cats = await list_categories(session)
    assert len(cats) == 2
    assert cats[0].name == "A"


async def test_update_category(session: AsyncSession) -> None:
    cat = await create_category(session, CategoryCreate(name="Old"))
    updated = await update_category(session, cat.id, CategoryUpdate(name="New"))
    assert updated.name == "New"


async def test_self_parent_rejected(session: AsyncSession) -> None:
    cat = await create_category(session, CategoryCreate(name="X"))
    with pytest.raises(HTTPException) as exc:
        await update_category(session, cat.id, CategoryUpdate(parent_id=cat.id))
    assert exc.value.status_code == 400
    assert "own parent" in exc.value.detail


async def test_cycle_rejected(session: AsyncSession) -> None:
    a = await create_category(session, CategoryCreate(name="A"))
    b = await create_category(session, CategoryCreate(name="B", parent_id=a.id))
    c = await create_category(session, CategoryCreate(name="C", parent_id=b.id))
    with pytest.raises(HTTPException) as exc:
        await update_category(session, a.id, CategoryUpdate(parent_id=c.id))
    assert exc.value.status_code == 400
    assert "cycle" in exc.value.detail


async def test_delete_category(session: AsyncSession) -> None:
    cat = await create_category(session, CategoryCreate(name="Temp"))
    await delete_category(session, cat.id)
    with pytest.raises(HTTPException) as exc:
        await get_category(session, cat.id)
    assert exc.value.status_code == 404
