from fastapi import APIRouter, Depends
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
