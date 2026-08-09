from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import async_session_factory, get_session
from finance.schemas.receipt import (
    OcrPreviewResponse,
    ReceiptRead,
    ReviewTransactionRequest,
    ToTransactionRequest,
)
from finance.schemas.transaction import TransactionDetail
from finance.services import receipt as receipt_service

router = APIRouter(
    prefix="/api/receipts",
    tags=["receipts"],
    dependencies=[Depends(current_user)],
)


@router.post("", response_model=ReceiptRead, status_code=201)
async def upload_receipt(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read()
    receipt, created = await receipt_service.store_upload(
        session,
        raw=raw,
        original_filename=file.filename or "receipt",
        content_type=file.content_type,
    )
    if created:
        background.add_task(
            receipt_service.process_in_background,
            async_session_factory,
            receipt.id,
        )
    return receipt


@router.get("/{receipt_id}", response_model=ReceiptRead)
async def get_receipt(
    receipt_id: int, session: AsyncSession = Depends(get_session)
):
    return await receipt_service.get_receipt(session, receipt_id)


@router.get("/{receipt_id}/image")
async def get_receipt_image(
    receipt_id: int, session: AsyncSession = Depends(get_session)
):
    receipt = await receipt_service.get_receipt(session, receipt_id)
    path = Path(receipt.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Receipt image missing on disk")
    return FileResponse(path, filename=receipt.original_filename)


@router.post("/{receipt_id}/process", response_model=ReceiptRead)
async def process_receipt(
    receipt_id: int,
    background: BackgroundTasks,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    receipt = await receipt_service.get_receipt(session, receipt_id)
    if receipt.ocr_status == "done" and not force:
        return receipt
    receipt.ocr_status = "pending"
    receipt.ocr_error = None
    await session.commit()
    await session.refresh(receipt)
    background.add_task(
        receipt_service.process_in_background,
        async_session_factory,
        receipt_id,
    )
    return receipt


@router.post("/{receipt_id}/to-transaction", response_model=TransactionDetail)
async def receipt_to_transaction(
    receipt_id: int,
    data: ToTransactionRequest,
    session: AsyncSession = Depends(get_session),
):
    return await receipt_service.materialize_transaction(
        session,
        receipt_id,
        account_id=data.account_id,
        merchant_id=data.merchant_id,
    )


@router.get("/{receipt_id}/ocr-preview", response_model=OcrPreviewResponse)
async def ocr_preview(
    receipt_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await receipt_service.build_ocr_preview(session, receipt_id)


@router.post("/{receipt_id}/review-to-transaction", response_model=TransactionDetail)
async def reviewed_receipt_to_transaction(
    receipt_id: int,
    data: ReviewTransactionRequest,
    session: AsyncSession = Depends(get_session),
):
    return await receipt_service.materialize_reviewed_transaction(
        session,
        receipt_id,
        account_id=data.account_id,
        merchant_name=data.merchant_name,
        merchant_id=data.merchant_id,
        posted_at=data.posted_at,
        total_cents=data.total_cents,
        items=[it.model_dump() for it in data.items],
    )
