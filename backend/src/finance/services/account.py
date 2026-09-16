from fastapi import HTTPException
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.models.account import Account
from finance.models.transaction import Transaction
from finance.schemas.account import AccountCreate, AccountUpdate

# Closed vocabulary for Account.type. Quicken's own account-type header
# (!Account / T<type>) maps onto this in scripts/retype_accounts.py.
CASH_FLOW_ACCOUNT_TYPES: frozenset[str] = frozenset(
    {"checking", "savings", "credit", "cash", "loan", "mortgage", "asset"}
)
INVESTMENT_ACCOUNT_TYPES: frozenset[str] = frozenset(
    {"brokerage", "ira", "roth_ira", "401k", "529", "hsa"}
)
ACCOUNT_TYPES: frozenset[str] = CASH_FLOW_ACCOUNT_TYPES | INVESTMENT_ACCOUNT_TYPES

# Investment accounts that are tax-advantaged. Lot holding period (short/long)
# and realized-gain reporting only matter for the complement: "brokerage".
TAX_ADVANTAGED_ACCOUNT_TYPES: frozenset[str] = frozenset({"ira", "roth_ira", "401k", "529", "hsa"})


def is_investment_type(account_type: str) -> bool:
    return account_type in INVESTMENT_ACCOUNT_TYPES


def excludes_investment_accounts() -> ColumnElement[bool]:
    """WHERE clause: the transaction's account is not an investment account.

    A correlated subquery rather than a join so callers can add it beside their
    existing ``Transaction.excluded.is_(None)`` filter without restructuring
    the statement (ADR 0006).
    """
    investment_ids = select(Account.id).where(Account.type.in_(INVESTMENT_ACCOUNT_TYPES))
    return Transaction.account_id.not_in(investment_ids)


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
