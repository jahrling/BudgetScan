from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from finance.models.account import Account
from finance.models.category import Category
from finance.models.line_item import LineItem
from finance.models.transaction import Transaction
from finance.schemas.line_item import LineItemCreate
from finance.schemas.transaction import TransactionCreate, TransactionUpdate
from finance.services.merchant import maybe_update_default_category


_SORT_COLUMNS = {
    "posted_at": Transaction.posted_at,
    "amount_cents": Transaction.amount_cents,
    "description": Transaction.description,
    "status": Transaction.status,
    "account_name": Account.name,
    "category_name": Category.name,
}


async def list_transactions(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account_id: int | None = None,
    status: str | None = None,
    category_id: int | None = None,
    sort_specs: list[tuple[str, str]] | None = None,
) -> tuple[list[Transaction], int]:
    q = select(Transaction)

    needs_account_join = False
    needs_category_join = False

    if sort_specs:
        for col_name, _ in sort_specs:
            if col_name == "account_name":
                needs_account_join = True
            elif col_name == "category_name":
                needs_category_join = True

    if needs_account_join:
        q = q.outerjoin(Account, Transaction.account_id == Account.id)
    if needs_category_join:
        q = q.outerjoin(Category, Transaction.category_id == Category.id)

    if date_from:
        q = q.where(Transaction.posted_at >= date_from)
    if date_to:
        q = q.where(Transaction.posted_at <= date_to)
    if account_id:
        q = q.where(Transaction.account_id == account_id)
    if status:
        q = q.where(Transaction.status == status)
    if category_id:
        sub = select(LineItem.transaction_id).where(
            LineItem.category_id == category_id
        ).distinct()
        q = q.where(Transaction.id.in_(sub))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    if sort_specs:
        for col_name, direction in sort_specs:
            col = _SORT_COLUMNS.get(col_name, Transaction.posted_at)
            q = q.order_by(col.asc() if direction == "asc" else col.desc())
    else:
        q = q.order_by(Transaction.posted_at.desc())

    q = q.offset(offset).limit(limit)
    result = await session.execute(q)
    return list(result.scalars().all()), total


async def get_transaction(session: AsyncSession, txn_id: int) -> Transaction:
    txn = await session.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


async def get_transaction_with_items(session: AsyncSession, txn_id: int) -> dict:
    txn = await get_transaction(session, txn_id)
    items_result = await session.execute(
        select(LineItem)
        .where(LineItem.transaction_id == txn_id)
        .order_by(LineItem.id)
    )
    items = list(items_result.scalars().all())
    line_items_data = []
    for li in items:
        cat = await session.get(Category, li.category_id)
        line_items_data.append({
            "id": li.id,
            "transaction_id": li.transaction_id,
            "category_id": li.category_id,
            "category_name": cat.name if cat else None,
            "description": li.description,
            "quantity": li.quantity,
            "unit_price_cents": li.unit_price_cents,
            "amount_cents": li.amount_cents,
            "ocr_confidence": li.ocr_confidence,
            "user_modified": li.user_modified,
            "created_at": li.created_at,
            "updated_at": li.updated_at,
        })

    return {
        "id": txn.id,
        "account_id": txn.account_id,
        "merchant_id": txn.merchant_id,
        "posted_at": txn.posted_at,
        "amount_cents": txn.amount_cents,
        "description": txn.description,
        "quicken_id": txn.quicken_id,
        "receipt_id": txn.receipt_id,
        "status": txn.status,
        "created_at": txn.created_at,
        "updated_at": txn.updated_at,
        "merchant_name": txn.merchant.name if txn.merchant else None,
        "line_items": line_items_data,
    }


async def create_transaction(
    session: AsyncSession, data: TransactionCreate
) -> dict:
    txn = Transaction(
        account_id=data.account_id,
        merchant_id=data.merchant_id,
        posted_at=data.posted_at,
        amount_cents=data.amount_cents,
        description=data.description,
        quicken_id=data.quicken_id,
        receipt_id=data.receipt_id,
        status=data.status,
    )
    session.add(txn)
    await session.flush()

    if data.line_items:
        items_total = sum(li.amount_cents for li in data.line_items)
        if items_total != data.amount_cents:
            raise HTTPException(
                status_code=400,
                detail=f"Line items sum ({items_total}) != transaction amount ({data.amount_cents})",
            )
        for li_data in data.line_items:
            li = LineItem(
                transaction_id=txn.id,
                category_id=li_data.category_id,
                description=li_data.description,
                quantity=li_data.quantity,
                unit_price_cents=li_data.unit_price_cents,
                amount_cents=li_data.amount_cents,
                ocr_confidence=li_data.ocr_confidence,
                user_modified=li_data.user_modified,
            )
            session.add(li)
        txn.status = "split"
    else:
        uncategorized = await _get_or_create_uncategorized(session)
        li = LineItem(
            transaction_id=txn.id,
            category_id=uncategorized.id,
            description=data.description,
            amount_cents=data.amount_cents,
        )
        session.add(li)

    await session.commit()
    await session.refresh(txn)

    if txn.merchant_id:
        await maybe_update_default_category(session, txn.merchant_id)

    return await get_transaction_with_items(session, txn.id)


async def update_transaction(
    session: AsyncSession, txn_id: int, data: TransactionUpdate
) -> Transaction:
    txn = await get_transaction(session, txn_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(txn, key, value)
    await session.commit()
    await session.refresh(txn)
    return txn


async def delete_transaction(session: AsyncSession, txn_id: int) -> None:
    txn = await get_transaction(session, txn_id)
    await session.execute(
        sa_delete(LineItem).where(LineItem.transaction_id == txn_id)
    )
    await session.delete(txn)
    await session.commit()


async def replace_line_items(
    session: AsyncSession,
    txn_id: int,
    items: list[LineItemCreate],
) -> list[dict]:
    txn = await get_transaction(session, txn_id)
    items_total = sum(li.amount_cents for li in items)
    if items_total != txn.amount_cents:
        raise HTTPException(
            status_code=400,
            detail=f"Line items sum ({items_total}) != transaction amount ({txn.amount_cents})",
        )

    await session.execute(
        sa_delete(LineItem).where(LineItem.transaction_id == txn_id)
    )

    for li_data in items:
        li = LineItem(
            transaction_id=txn_id,
            category_id=li_data.category_id,
            description=li_data.description,
            quantity=li_data.quantity,
            unit_price_cents=li_data.unit_price_cents,
            amount_cents=li_data.amount_cents,
            ocr_confidence=li_data.ocr_confidence,
            user_modified=li_data.user_modified,
        )
        session.add(li)

    txn.status = "split" if len(items) > 1 else "pending"
    await session.commit()

    if txn.merchant_id:
        await maybe_update_default_category(session, txn.merchant_id)

    items_result = await session.execute(
        select(LineItem)
        .where(LineItem.transaction_id == txn_id)
        .order_by(LineItem.id)
    )
    result_items = list(items_result.scalars().all())
    line_items_data = []
    for li in result_items:
        cat = await session.get(Category, li.category_id)
        line_items_data.append({
            "id": li.id,
            "transaction_id": li.transaction_id,
            "category_id": li.category_id,
            "category_name": cat.name if cat else None,
            "description": li.description,
            "quantity": li.quantity,
            "unit_price_cents": li.unit_price_cents,
            "amount_cents": li.amount_cents,
            "ocr_confidence": li.ocr_confidence,
            "user_modified": li.user_modified,
            "created_at": li.created_at,
            "updated_at": li.updated_at,
        })
    return line_items_data


async def _get_or_create_uncategorized(session: AsyncSession) -> Category:
    result = await session.execute(
        select(Category).where(Category.name == "Uncategorized")
    )
    cat = result.scalar_one_or_none()
    if cat is None:
        cat = Category(name="Uncategorized")
        session.add(cat)
        await session.flush()
    return cat
