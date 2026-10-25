from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.account import Account
from finance.services.embeddings import default_embedder
from finance.services.vector_store import rebuild_rules_index
from finance.schemas.quicken import (
    CategoryDefinitionSchema,
    ConfirmRequest,
    ConfirmResponse,
    MemorizedRuleSchema,
    ParseResultSchema,
    ReconciliationSchema,
    RuleConflictSchema,
    RulePersistResultSchema,
    SplitCandidateSchema,
    StatementParseResultSchema,
    StatementPdfJobSchema,
    TransactionCandidateSchema,
)
from finance.services import quicken as svc
from finance.services import statement_import, statement_pdf

_MAX_STATEMENT_BYTES = 5 * 1024 * 1024

import_router = APIRouter(
    prefix="/api/import",
    tags=["import"],
    dependencies=[Depends(current_user)],
)

export_router = APIRouter(
    prefix="/api/export",
    tags=["export"],
    dependencies=[Depends(current_user)],
)


def _to_schema(result: svc.ParseResult) -> ParseResultSchema:
    return ParseResultSchema(
        candidates=[
            TransactionCandidateSchema(
                source_account_key=c.source_account_key,
                account_id=c.account_id,
                posted_at=c.posted_at,
                amount_cents=c.amount_cents,
                description=c.description,
                quicken_id=c.quicken_id,
                currency=c.currency,
                splits=[
                    SplitCandidateSchema(
                        category_path=s.category_path,
                        amount_cents=s.amount_cents,
                        description=s.description,
                    )
                    for s in c.splits
                ],
                cleared=c.cleared,
                transfer_account=c.transfer_account,
                match_status=c.match_status,
                match_transaction_id=c.match_transaction_id,
                match_description=c.match_description,
                match_amount_cents=c.match_amount_cents,
                match_posted_at=c.match_posted_at,
                match_category_path=c.match_category_path,
            )
            for c in result.candidates
        ],
        unmapped_accounts=result.unmapped_accounts,
        errors=result.errors,
        categories=[
            CategoryDefinitionSchema(
                name=cat.name,
                description=cat.description,
                is_income=cat.is_income,
                tax_related=cat.tax_related,
                tax_schedule=cat.tax_schedule,
            )
            for cat in result.categories
        ],
        memorized_rules=[
            MemorizedRuleSchema(
                payee=r.payee,
                category_path=r.category_path,
                amount_cents=r.amount_cents,
                transfer_account=r.transfer_account,
                kind=r.kind,
            )
            for r in result.memorized_rules
        ],
    )


@import_router.post("/qfx", response_model=ParseResultSchema)
async def import_qfx(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    data = await file.read()
    result = await svc.import_qfx(data, session)
    await svc.match_candidates(session, result.candidates)
    return _to_schema(result)


@import_router.post("/statement", response_model=StatementParseResultSchema)
async def import_statement(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    invert: bool | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """Parse a card/bank statement (CSV or QFX/OFX) for one chosen account.

    Returns candidates for review; nothing is written until /confirm.
    """
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    data = await file.read(_MAX_STATEMENT_BYTES + 1)
    if len(data) > _MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=413, detail="Statement file too large (max 5 MB)")
    try:
        result = await statement_import.parse_statement(
            data, file.filename, account, session, invert=invert
        )
    except statement_import.UnsupportedStatementError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    await svc.match_candidates(session, result.candidates)
    return _to_statement_schema(result)


def _to_statement_schema(
    result: statement_import.StatementParseResult,
) -> StatementParseResultSchema:
    return StatementParseResultSchema(
        **_to_schema(result).model_dump(),
        format=result.format,
        inverted=result.inverted,
        columns=result.columns,
    )


def _to_job_schema(job: statement_pdf.PdfJob) -> StatementPdfJobSchema:
    return StatementPdfJobSchema(
        job_id=job.id,
        status=job.status,
        pages_done=job.pages_done,
        pages_total=job.pages_total,
        error=job.error,
        result=_to_statement_schema(job.result) if job.result else None,
        reconciliation=(
            ReconciliationSchema(**asdict(job.reconciliation)) if job.reconciliation else None
        ),
    )


@import_router.post("/statement-pdf", response_model=StatementPdfJobSchema, status_code=202)
async def import_statement_pdf(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Start parsing a PDF statement with the local LLM; poll the GET below.

    The PDF is held in memory only for the job's duration, never stored.
    """
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    data = await file.read(_MAX_STATEMENT_BYTES + 1)
    if len(data) > _MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=413, detail="Statement file too large (max 5 MB)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Not a PDF file")
    return _to_job_schema(statement_pdf.start_job(data, account))


@import_router.get("/statement-pdf/{job_id}", response_model=StatementPdfJobSchema)
async def get_statement_pdf_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    job = statement_pdf.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Parse job not found (it may have expired or the server restarted). Upload again.",
        )
    if job.status == "done" and job.result and not job.matched:
        job.matched = True  # before the await, so overlapping polls don't re-match
        await svc.match_candidates(session, job.result.candidates)
    return _to_job_schema(job)


@import_router.post("/qif", response_model=ParseResultSchema)
async def import_qif(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    data = await file.read()
    result = await svc.import_qif(data, session)
    await svc.match_candidates(session, result.candidates)

    if result.categories:
        await svc.ensure_parsed_categories(session, result.categories)
        await session.commit()

    schema = _to_schema(result)

    if result.memorized_rules:
        persist_result = await svc.persist_memorized_rules(
            session, result.memorized_rules
        )
        schema.rule_persist_result = RulePersistResultSchema(
            created=persist_result.created,
            updated=persist_result.updated,
            unchanged=persist_result.unchanged,
            conflicts=[
                RuleConflictSchema(
                    incoming_payee=c.incoming_payee,
                    incoming_category_path=c.incoming_category_path,
                    existing_rule_id=c.existing_rule_id,
                    existing_category_path=c.existing_category_path,
                    existing_match_count=c.existing_match_count,
                )
                for c in persist_result.conflicts
            ],
        )
        await session.commit()

        if persist_result.created > 0 or persist_result.updated > 0:
            try:
                await rebuild_rules_index(session, default_embedder())
            except Exception:
                pass

    return schema


@import_router.post("/confirm", response_model=ConfirmResponse)
async def confirm_import(
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_session),
):
    candidates = [
        svc.TransactionCandidate(
            source_account_key=c.source_account_key,
            account_id=c.account_id,
            posted_at=c.posted_at,
            amount_cents=c.amount_cents,
            description=c.description,
            quicken_id=c.quicken_id,
            currency=c.currency,
            splits=[
                svc.SplitCandidate(
                    category_path=s.category_path,
                    amount_cents=s.amount_cents,
                    description=s.description,
                )
                for s in c.splits
            ],
            match_status=c.match_status,
            match_transaction_id=c.match_transaction_id,
        )
        for c in body.candidates
    ]
    actions = [
        svc.ConfirmAction(candidate_index=a.candidate_index, action=a.action)
        for a in body.actions
    ]
    result = await svc.apply_confirmations(
        session,
        candidates,
        actions,
        create_missing_categories=body.create_missing_categories,
    )
    return ConfirmResponse(
        created_ids=result.created_ids,
        merged_ids=result.merged_ids,
        overwritten_ids=result.overwritten_ids,
        skipped=result.skipped,
        errors=result.errors,
    )


@export_router.get("/qif", response_class=PlainTextResponse)
async def export_qif(
    accounts: Annotated[list[int], Query()],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    session: AsyncSession = Depends(get_session),
):
    from finance.models.transaction import Transaction

    if not accounts:
        raise HTTPException(status_code=400, detail="At least one account required")

    parts: list[str] = []
    for account_id in accounts:
        account = await session.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

        q = select(Transaction.id).where(Transaction.account_id == account_id)
        if date_from:
            q = q.where(Transaction.posted_at >= date_from)
        if date_to:
            q = q.where(Transaction.posted_at <= date_to)
        ids_result = await session.execute(q.order_by(Transaction.posted_at))
        txn_ids = [r[0] for r in ids_result.all()]
        parts.append(await svc.export_qif(session, txn_ids, account))

    body = "\n".join(parts)
    return PlainTextResponse(
        content=body,
        headers={
            "Content-Disposition": 'attachment; filename="finance-export.qif"',
            "Content-Type": "application/qif; charset=utf-8",
        },
    )
