from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.schemas.account import AccountCreate, AccountUpdate


async def list_accounts(session: AsyncSession) -> list[Account]:
    result = await session.execute(select(Account).order_by(Account.name))
    return list(result.scalars().all())


async def get_account(session: AsyncSession, account_id: int) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def create_account(session: AsyncSession, data: AccountCreate) -> Account:
    account = Account(**data.model_dump())
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def update_account(
    session: AsyncSession, account_id: int, data: AccountUpdate
) -> Account:
    account = await get_account(session, account_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    await session.commit()
    await session.refresh(account)
    return account


async def delete_account(session: AsyncSession, account_id: int) -> None:
    account = await get_account(session, account_id)
    await session.delete(account)
    await session.commit()
