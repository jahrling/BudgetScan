from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.transaction import Transaction
from finance.schemas.line_item import LineItemRead, LineItemsReplace
from finance.schemas.transaction import (
    TransactionCreate,
    TransactionDetail,
    TransactionRead,
    TransactionUpdate,
)
from finance.services import transaction as txn_service
from finance.services.categorization_pipeline import categorize
from finance.services.embeddings import default_embedder

router = APIRouter(
    prefix="/api/transactions",
    tags=["transactions"],
    dependencies=[Depends(current_user)],
)


@router.get("")
async def list_transactions(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account_id: int | None = None,
    status: str | None = None,
    category_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    txns, total = await txn_service.list_transactions(
        session,
        offset=offset,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        status=status,
        category_id=category_id,
    )
    items = []
    for t in txns:
        items.append(
            TransactionRead(
                id=t.id,
                account_id=t.account_id,
                merchant_id=t.merchant_id,
                posted_at=t.posted_at,
                amount_cents=t.amount_cents,
                description=t.description,
                quicken_id=t.quicken_id,
                receipt_id=t.receipt_id,
                status=t.status,
                created_at=t.created_at,
                updated_at=t.updated_at,
                merchant_name=t.merchant.name if t.merchant else None,
            )
        )
    return {"items": items, "total": total}


@router.get("/{txn_id}", response_model=TransactionDetail)
async def get_transaction(
    txn_id: int, session: AsyncSession = Depends(get_session)
):
    return await txn_service.get_transaction_with_items(session, txn_id)


@router.post("", response_model=TransactionDetail, status_code=201)
async def create_transaction(
    data: TransactionCreate, session: AsyncSession = Depends(get_session)
):
    return await txn_service.create_transaction(session, data)


@router.patch("/{txn_id}", response_model=TransactionRead)
async def update_transaction(
    txn_id: int,
    data: TransactionUpdate,
    session: AsyncSession = Depends(get_session),
):
    txn = await txn_service.update_transaction(session, txn_id, data)
    return TransactionRead(
        id=txn.id,
        account_id=txn.account_id,
        merchant_id=txn.merchant_id,
        posted_at=txn.posted_at,
        amount_cents=txn.amount_cents,
        description=txn.description,
        quicken_id=txn.quicken_id,
        receipt_id=txn.receipt_id,
        status=txn.status,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
        merchant_name=txn.merchant.name if txn.merchant else None,
    )


@router.delete("/{txn_id}", status_code=204)
async def delete_transaction(
    txn_id: int, session: AsyncSession = Depends(get_session)
):
    await txn_service.delete_transaction(session, txn_id)


@router.put("/{txn_id}/line_items", response_model=list[LineItemRead])
async def replace_line_items(
    txn_id: int,
    data: LineItemsReplace,
    session: AsyncSession = Depends(get_session),
):
    return await txn_service.replace_line_items(session, txn_id, data.line_items)


class CategorizeRequest(BaseModel):
    transaction_ids: list[int] | None = None
    limit: int = 50
    skip_llm: bool = False


class CategorizedTransaction(BaseModel):
    transaction_id: int
    category_id: int | None
    confidence: float
    source: str
    tier: str
    needs_review: bool
    merchant_guess: str | None = None


class CategorizeResponse(BaseModel):
    results: list[CategorizedTransaction]
    processed: int
    skipped: int


@router.post("/categorize", response_model=CategorizeResponse)
async def categorize_transactions(
    body: CategorizeRequest,
    session: AsyncSession = Depends(get_session),
):
    """Run the categorization pipeline on uncategorized transactions.

    If ``transaction_ids`` is provided, only those transactions are processed.
    Otherwise processes up to ``limit`` transactions that have no category set.
    """
    embedder = default_embedder()

    if body.transaction_ids:
        stmt = select(Transaction).where(Transaction.id.in_(body.transaction_ids))
    else:
        stmt = (
            select(Transaction)
            .where(Transaction.category_id.is_(None))
            .where(Transaction.description.isnot(None))
            .order_by(Transaction.posted_at.desc())
            .limit(body.limit)
        )

    txns = list((await session.execute(stmt)).scalars().all())
    results: list[CategorizedTransaction] = []
    skipped = 0

    for txn in txns:
        if not txn.description:
            skipped += 1
            continue

        resolved_merchant = None
        if txn.merchant and txn.merchant.resolved_name:
            resolved_merchant = txn.merchant.resolved_name

        result = await categorize(
            session,
            txn.description,
            txn.amount_cents,
            resolved_merchant=resolved_merchant,
            embedder=embedder,
            skip_llm=body.skip_llm,
        )

        txn.category_id = result.category_id
        txn.category_confidence = result.confidence
        txn.category_source = result.source
        txn.needs_review = result.needs_review

        results.append(
            CategorizedTransaction(
                transaction_id=txn.id,
                category_id=result.category_id,
                confidence=result.confidence,
                source=result.source,
                tier=result.tier,
                needs_review=result.needs_review,
                merchant_guess=result.merchant_guess,
            )
        )

    await session.commit()
    return CategorizeResponse(
        results=results,
        processed=len(results),
        skipped=skipped,
    )
