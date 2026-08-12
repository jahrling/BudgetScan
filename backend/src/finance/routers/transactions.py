from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.category import Category
from finance.models.memorized_rule import MemorizedRule
from finance.models.merchant import Merchant
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
from finance.services.merchant_resolver import (
    clean_description,
    normalize_for_matching,
)

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
    sort_by: str | None = None,
    sort_dir: str = "desc",
    sort: str | None = Query(None, description="Multi-sort: 'col1:asc,col2:desc'"),
    session: AsyncSession = Depends(get_session),
):
    sort_specs: list[tuple[str, str]] | None = None
    if sort:
        sort_specs = []
        for part in sort.split(","):
            parts = part.strip().split(":")
            col_name = parts[0]
            direction = parts[1] if len(parts) > 1 else "asc"
            if col_name and direction in ("asc", "desc"):
                sort_specs.append((col_name, direction))
    elif sort_by:
        sort_specs = [(sort_by, sort_dir)]

    txns, total = await txn_service.list_transactions(
        session,
        offset=offset,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        status=status,
        category_id=category_id,
        sort_specs=sort_specs,
    )

    # Batch-resolve counterpart account names for transfer pairs
    pair_ids = [t.transfer_pair_id for t in txns if t.transfer_pair_id]
    counterpart_map: dict[int, str] = {}
    if pair_ids:
        partner_q = (
            select(Transaction)
            .where(Transaction.transfer_pair_id.in_(pair_ids))
        )
        partners = list((await session.execute(partner_q)).scalars().all())
        by_pair: dict[int, list[Transaction]] = {}
        for p in partners:
            by_pair.setdefault(p.transfer_pair_id, []).append(p)
        for t in txns:
            if not t.transfer_pair_id:
                continue
            group = by_pair.get(t.transfer_pair_id, [])
            other = next((p for p in group if p.id != t.id), None)
            if other and other.account:
                counterpart_map[t.id] = other.account.name

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
                transfer_pair_id=t.transfer_pair_id,
                created_at=t.created_at,
                updated_at=t.updated_at,
                merchant_name=t.merchant.name if t.merchant else None,
                account_name=t.account.name if t.account else None,
                category_name=t.category.name if t.category else None,
                transfer_account_name=counterpart_map.get(t.id),
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

        result = await categorize(
            session,
            txn.description,
            txn.amount_cents,
            embedder=embedder,
            skip_llm=body.skip_llm,
        )

        txn.category_id = result.category_id
        txn.category_confidence = result.confidence
        txn.category_source = result.source
        txn.needs_review = result.needs_review

        if result.resolved_merchant and result.resolved_merchant.merchant_id:
            txn.merchant_id = result.resolved_merchant.merchant_id

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


class ConfirmCategoryRequest(BaseModel):
    category_id: int
    merchant_name: str | None = None


class ConfirmCategoryResponse(BaseModel):
    transaction_id: int
    category_id: int
    rule_id: int | None = None
    merchant_updated: bool = False


def _build_category_path(cat) -> str:
    parts = [cat.name]
    parent = cat.parent
    while parent is not None:
        parts.append(parent.name)
        parent = parent.parent
    return ":".join(reversed(parts))


@router.post("/{txn_id}/confirm-category", response_model=ConfirmCategoryResponse)
async def confirm_category(
    txn_id: int,
    body: ConfirmCategoryRequest,
    session: AsyncSession = Depends(get_session),
):
    """Confirm or correct a transaction's category.

    This is the feedback loop: the user's choice is recorded on the
    transaction and feeds back into the categorization system by
    creating/updating a MemorizedRule and optionally updating the
    merchant's resolved_name.
    """
    txn = await txn_service.get_transaction(session, txn_id)
    cat = await session.get(Category, body.category_id)
    if cat is None:
        raise HTTPException(status_code=400, detail="Category not found")

    # Update the transaction
    txn.category_id = body.category_id
    txn.category_source = "user"
    txn.category_confidence = 1.0
    txn.needs_review = False

    category_path = _build_category_path(cat)
    rule_id = None

    # Create or update a MemorizedRule for this payee
    if txn.description:
        cleaned = clean_description(txn.description)
        normalized = normalize_for_matching(cleaned or txn.description)

        if normalized:
            stmt = (
                select(MemorizedRule)
                .where(MemorizedRule.normalized_payee == normalized)
                .where(MemorizedRule.status == "active")
            )
            existing_rules = list(
                (await session.execute(stmt)).scalars().all()
            )

            user_rules = [r for r in existing_rules if r.source == "user_created"]

            if user_rules:
                rule = user_rules[0]
                rule.category_path = category_path
                rule.category_id = body.category_id
                rule_id = rule.id
            else:
                rule = MemorizedRule(
                    payee=cleaned or txn.description,
                    normalized_payee=normalized,
                    category_path=category_path,
                    category_id=body.category_id,
                    source="user_created",
                    status="active",
                )
                session.add(rule)
                await session.flush()
                rule_id = rule.id

    # Update merchant resolved_name if provided
    merchant_updated = False
    if body.merchant_name and txn.merchant_id:
        merchant = await session.get(Merchant, txn.merchant_id)
        if merchant is not None:
            merchant.resolved_name = body.merchant_name
            merchant.resolution_source = "user"
            merchant.resolution_confidence = 1.0
            merchant_updated = True
    elif body.merchant_name and txn.description:
        cleaned = clean_description(txn.description)
        if cleaned:
            normalized = normalize_for_matching(cleaned)
            stmt = select(Merchant).where(Merchant.normalized_name == normalized)
            merchant = (await session.execute(stmt)).scalars().first()
            if merchant is not None:
                merchant.resolved_name = body.merchant_name
                merchant.resolution_source = "user"
                merchant.resolution_confidence = 1.0
                txn.merchant_id = merchant.id
                merchant_updated = True

    await session.commit()

    return ConfirmCategoryResponse(
        transaction_id=txn.id,
        category_id=body.category_id,
        rule_id=rule_id,
        merchant_updated=merchant_updated,
    )


class BackfillResponse(BaseModel):
    updated: int
    already_set: int


@router.post("/backfill-categories", response_model=BackfillResponse)
async def backfill_categories(
    session: AsyncSession = Depends(get_session),
):
    """Backfill Transaction.category_id from single-LineItem transactions.

    Fixes transactions imported before category_id was set at the
    transaction level.
    """
    from finance.models.line_item import LineItem as LI
    from sqlalchemy import func as sqlfunc

    single_item_txns = (
        select(LI.transaction_id, LI.category_id)
        .group_by(LI.transaction_id)
        .having(sqlfunc.count(LI.id) == 1)
    ).subquery()

    stmt = (
        select(Transaction)
        .join(single_item_txns, Transaction.id == single_item_txns.c.transaction_id)
        .where(Transaction.category_id.is_(None))
    )
    txns = list((await session.execute(stmt)).scalars().all())

    updated = 0
    for txn in txns:
        li_result = await session.execute(
            select(LI).where(LI.transaction_id == txn.id).limit(1)
        )
        li = li_result.scalar_one_or_none()
        if li and li.category_id:
            txn.category_id = li.category_id
            txn.category_source = txn.category_source or "backfill"
            txn.needs_review = False
            updated += 1

    if updated:
        await session.commit()

    already_set_q = select(sqlfunc.count()).select_from(
        select(Transaction).where(Transaction.category_id.isnot(None)).subquery()
    )
    already_set = (await session.execute(already_set_q)).scalar() or 0

    return BackfillResponse(updated=updated, already_set=already_set)
