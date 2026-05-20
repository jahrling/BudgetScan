from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.line_item import LineItem
from finance.models.merchant import Merchant
from finance.models.transaction import Transaction
from finance.schemas.merchant import MerchantCreate, MerchantUpdate

LEARNING_THRESHOLD = 3


def _normalize(name: str) -> str:
    return name.strip().lower()


async def list_merchants(session: AsyncSession) -> list[Merchant]:
    result = await session.execute(select(Merchant).order_by(Merchant.name))
    return list(result.scalars().all())


async def search_merchants(session: AsyncSession, q: str) -> list[Merchant]:
    pattern = f"%{_normalize(q)}%"
    result = await session.execute(
        select(Merchant)
        .where(Merchant.normalized_name.like(pattern))
        .order_by(Merchant.name)
        .limit(20)
    )
    return list(result.scalars().all())


async def get_merchant(session: AsyncSession, merchant_id: int) -> Merchant:
    merchant = await session.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant


async def create_merchant(session: AsyncSession, data: MerchantCreate) -> Merchant:
    merchant = Merchant(
        name=data.name,
        normalized_name=_normalize(data.name),
        default_category_id=data.default_category_id,
        notes=data.notes,
    )
    session.add(merchant)
    await session.commit()
    await session.refresh(merchant)
    return merchant


async def update_merchant(
    session: AsyncSession, merchant_id: int, data: MerchantUpdate
) -> Merchant:
    merchant = await get_merchant(session, merchant_id)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["normalized_name"] = _normalize(updates["name"])
    for key, value in updates.items():
        setattr(merchant, key, value)
    await session.commit()
    await session.refresh(merchant)
    return merchant


async def delete_merchant(session: AsyncSession, merchant_id: int) -> None:
    merchant = await get_merchant(session, merchant_id)
    await session.delete(merchant)
    await session.commit()


async def maybe_update_default_category(
    session: AsyncSession, merchant_id: int
) -> None:
    count_result = await session.execute(
        select(func.count(Transaction.id.distinct())).where(
            Transaction.merchant_id == merchant_id
        )
    )
    txn_count = count_result.scalar() or 0
    if txn_count < LEARNING_THRESHOLD:
        return

    most_common = await session.execute(
        select(
            LineItem.category_id,
            func.count(LineItem.id).label("cnt"),
        )
        .join(Transaction, LineItem.transaction_id == Transaction.id)
        .where(Transaction.merchant_id == merchant_id)
        .group_by(LineItem.category_id)
        .order_by(func.count(LineItem.id).desc())
        .limit(1)
    )
    row = most_common.first()
    if row is None:
        return

    merchant = await session.get(Merchant, merchant_id)
    if merchant is not None:
        merchant.default_category_id = row.category_id
        await session.commit()
