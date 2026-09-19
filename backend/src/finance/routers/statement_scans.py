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
from finance.schemas.statement_scan import (
    MaterializeRequest,
    StatementReviewPreview,
    StatementScanRead,
)
from finance.schemas.investment import PositionSnapshotRead
from finance.services import statement_scan as scan_service

router = APIRouter(
    prefix="/api/statement-scans",
    tags=["statement-scans"],
    dependencies=[Depends(current_user)],
)


@router.post("", response_model=StatementScanRead, status_code=201)
async def upload_statement(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    raw = await file.read()
    scan, created = await scan_service.store_upload(
        session,
        raw=raw,
        original_filename=file.filename or "statement",
        content_type=file.content_type,
    )
    if created:
        background.add_task(
            scan_service.process_in_background,
            async_session_factory,
            scan.id,
        )
    return scan


@router.get("/{scan_id}", response_model=StatementScanRead)
async def get_scan(
    scan_id: int, session: AsyncSession = Depends(get_session)
):
    return await scan_service.get_scan(session, scan_id)


@router.get("/{scan_id}/image")
async def get_scan_image(
    scan_id: int, session: AsyncSession = Depends(get_session)
):
    scan = await scan_service.get_scan(session, scan_id)
    path = Path(scan.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Statement image missing on disk")
    return FileResponse(path, filename=scan.original_filename)


@router.post("/{scan_id}/reprocess", response_model=StatementScanRead)
async def reprocess_scan(
    scan_id: int,
    background: BackgroundTasks,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    scan = await scan_service.get_scan(session, scan_id)
    if scan.ocr_status == "pending" and not force:
        return scan
    scan.ocr_status = "pending"
    scan.ocr_error = None
    await session.commit()
    await session.refresh(scan)
    background.add_task(
        scan_service.process_in_background,
        async_session_factory,
        scan.id,
    )
    return scan


@router.get("/{scan_id}/preview", response_model=StatementReviewPreview)
async def get_preview(
    scan_id: int, session: AsyncSession = Depends(get_session)
):
    return await scan_service.build_review_preview(session, scan_id)


@router.post(
    "/{scan_id}/materialize",
    response_model=list[PositionSnapshotRead],
    status_code=201,
)
async def materialize(
    scan_id: int,
    body: MaterializeRequest,
    session: AsyncSession = Depends(get_session),
):
    return await scan_service.materialize_snapshots(
        session,
        scan_id,
        account_id=body.account_id,
        as_of=body.as_of,
        positions=[p.model_dump() for p in body.positions],
    )
