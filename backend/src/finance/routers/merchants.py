from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.schemas.merchant import MerchantCreate, MerchantRead, MerchantUpdate
from finance.services import merchant as merchant_service

router = APIRouter(
    prefix="/api/merchants",
    tags=["merchants"],
    dependencies=[Depends(current_user)],
)


@router.get("", response_model=list[MerchantRead])
async def list_merchants(session: AsyncSession = Depends(get_session)):
    merchants = await merchant_service.list_merchants(session)
    return [_to_read(m) for m in merchants]


@router.get("/search", response_model=list[MerchantRead])
async def search_merchants(
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
):
    merchants = await merchant_service.search_merchants(session, q)
    return [_to_read(m) for m in merchants]


@router.get("/{merchant_id}", response_model=MerchantRead)
async def get_merchant(
    merchant_id: int, session: AsyncSession = Depends(get_session)
):
    m = await merchant_service.get_merchant(session, merchant_id)
    return _to_read(m)


@router.post("", response_model=MerchantRead, status_code=201)
async def create_merchant(
    data: MerchantCreate, session: AsyncSession = Depends(get_session)
):
    m = await merchant_service.create_merchant(session, data)
    return _to_read(m)


@router.patch("/{merchant_id}", response_model=MerchantRead)
async def update_merchant(
    merchant_id: int,
    data: MerchantUpdate,
    session: AsyncSession = Depends(get_session),
):
    m = await merchant_service.update_merchant(session, merchant_id, data)
    return _to_read(m)


@router.delete("/{merchant_id}", status_code=204)
async def delete_merchant(
    merchant_id: int, session: AsyncSession = Depends(get_session)
):
    await merchant_service.delete_merchant(session, merchant_id)


def _to_read(m):
    return MerchantRead(
        id=m.id,
        name=m.name,
        normalized_name=m.normalized_name,
        default_category_id=m.default_category_id,
        default_category_name=m.default_category.name if m.default_category else None,
        notes=m.notes,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
