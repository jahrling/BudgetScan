from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.annotation import Annotation
from finance.schemas.annotation import AnnotationCreate, AnnotationRead

router = APIRouter(
    prefix="/api/annotations",
    tags=["annotations"],
    dependencies=[Depends(current_user)],
)


@router.get("", response_model=list[AnnotationRead])
async def list_annotations(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Annotation).order_by(Annotation.id.desc()))
    return list(rows.scalars().all())


@router.post("", response_model=AnnotationRead, status_code=201)
async def create_annotation(
    data: AnnotationCreate, session: AsyncSession = Depends(get_session)
):
    ann = Annotation(text=data.text, transaction_id=data.transaction_id)
    session.add(ann)
    await session.commit()
    await session.refresh(ann)
    return ann
