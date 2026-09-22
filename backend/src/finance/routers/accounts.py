from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.schemas.account import AccountCreate, AccountRead, AccountUpdate
from finance.services import account as account_service

router = APIRouter(
    prefix="/api/accounts",
    tags=["accounts"],
    dependencies=[Depends(current_user)],
)


@router.get("", response_model=list[AccountRead])
async def list_accounts(session: AsyncSession = Depends(get_session)):
    return await account_service.list_accounts(session)


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: int, session: AsyncSession = Depends(get_session)
):
    return await account_service.get_account(session, account_id)


@router.post("", response_model=AccountRead, status_code=201)
async def create_account(
    data: AccountCreate, session: AsyncSession = Depends(get_session)
):
    return await account_service.create_account(session, data)


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    data: AccountUpdate,
    session: AsyncSession = Depends(get_session),
):
    return await account_service.update_account(session, account_id, data)


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: int, session: AsyncSession = Depends(get_session)
):
    await account_service.delete_account(session, account_id)


class MergeRequest(BaseModel):
    source_id: int
    target_id: int


class MergeResponse(BaseModel):
    target_id: int
    source_deleted: bool
    rows_reassigned: dict[str, int]


@router.post("/merge", response_model=MergeResponse)
async def merge_accounts(
    body: MergeRequest, session: AsyncSession = Depends(get_session)
):
    """Merge source account into target: reassign all FK references, delete source."""
    if body.source_id == body.target_id:
        raise HTTPException(400, "Cannot merge an account into itself")

    from finance.models.account import Account
    from finance.models.investment_transaction import InvestmentTransaction
    from finance.models.lot import Lot
    from finance.models.position_snapshot import PositionSnapshot
    from finance.models.statement_scan import StatementScan
    from finance.models.transaction import Transaction

    source = await session.get(Account, body.source_id)
    target = await session.get(Account, body.target_id)
    if source is None or target is None:
        raise HTTPException(404, "One or both accounts not found")

    fk_tables: list[tuple[str, type]] = [
        ("transactions", Transaction),
        ("investment_transactions", InvestmentTransaction),
        ("lots", Lot),
        ("position_snapshots", PositionSnapshot),
        ("statement_scans", StatementScan),
    ]

    rows_reassigned: dict[str, int] = {}
    for label, model in fk_tables:
        result = await session.execute(
            update(model)
            .where(model.account_id == body.source_id)
            .values(account_id=body.target_id)
        )
        if result.rowcount > 0:
            rows_reassigned[label] = result.rowcount

    await session.delete(source)
    await session.commit()

    return MergeResponse(
        target_id=body.target_id,
        source_deleted=True,
        rows_reassigned=rows_reassigned,
    )
