from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.services.transfer_detector import (
    clear_transfer_pair,
    detect_transfers,
    list_transfer_pairs,
)

router = APIRouter(
    prefix="/api/transfers",
    tags=["transfers"],
    dependencies=[Depends(current_user)],
)


class DetectRequest(BaseModel):
    account_ids: list[int] | None = None
    window_days: int = 3
    dry_run: bool = False


class DetectResponse(BaseModel):
    new_pairs: int
    cleared_pairs: int
    total_pairs: int


class TransferPairRead(BaseModel):
    pair_id: int
    debit_txn_id: int
    credit_txn_id: int
    debit_account_id: int
    credit_account_id: int
    debit_account_name: str | None = None
    credit_account_name: str | None = None
    amount_cents: int
    debit_description: str | None
    credit_description: str | None
    debit_posted_at: str
    credit_posted_at: str


class TransferListResponse(BaseModel):
    items: list[TransferPairRead]
    total: int


@router.post("/detect", response_model=DetectResponse)
async def detect(
    body: DetectRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await detect_transfers(
        session,
        account_ids=body.account_ids,
        window_days=body.window_days,
        dry_run=body.dry_run,
    )
    return DetectResponse(
        new_pairs=result.new_pairs,
        cleared_pairs=result.cleared_pairs,
        total_pairs=result.total_pairs,
    )


@router.get("", response_model=TransferListResponse)
async def list_pairs(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    from finance.models.account import Account

    pairs, total = await list_transfer_pairs(session, offset=offset, limit=limit)
    account_ids = set()
    for p in pairs:
        account_ids.add(p.debit_account_id)
        account_ids.add(p.credit_account_id)

    acct_map: dict[int, str] = {}
    if account_ids:
        from sqlalchemy import select
        rows = (
            await session.execute(
                select(Account).where(Account.id.in_(account_ids))
            )
        ).scalars().all()
        acct_map = {a.id: a.name for a in rows}

    items = [
        TransferPairRead(
            pair_id=p.pair_id,
            debit_txn_id=p.debit_txn_id,
            credit_txn_id=p.credit_txn_id,
            debit_account_id=p.debit_account_id,
            credit_account_id=p.credit_account_id,
            debit_account_name=acct_map.get(p.debit_account_id),
            credit_account_name=acct_map.get(p.credit_account_id),
            amount_cents=p.amount_cents,
            debit_description=p.debit_description,
            credit_description=p.credit_description,
            debit_posted_at=p.debit_posted_at,
            credit_posted_at=p.credit_posted_at,
        )
        for p in pairs
    ]
    return TransferListResponse(items=items, total=total)


@router.delete("/{pair_id}")
async def remove_pair(
    pair_id: int,
    session: AsyncSession = Depends(get_session),
):
    cleared = await clear_transfer_pair(session, pair_id)
    return {"cleared": cleared}
