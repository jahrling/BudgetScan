from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.models.category import Category
from finance.models.memorized_rule import MemorizedRule
from finance.models.transaction import Transaction
from finance.schemas.rules import (
    BulkActionResponse,
    BulkActivateRequest,
    DraftGenerationResponse,
    MonthlyRunResponse,
    RuleCreate,
    RuleListResponse,
    RulePreviewMatch,
    RulePreviewRequest,
    RulePreviewResponse,
    RuleReindexResponse,
    RuleResponse,
    RuleSeedResponse,
    RuleUpdate,
)
from finance.services.embeddings import default_embedder
from finance.services.merchant_resolver import normalize_for_matching
from finance.services.vector_store import rebuild_rules_index

router = APIRouter(
    prefix="/api/rules",
    tags=["rules"],
    dependencies=[Depends(current_user)],
)


def _category_path(cat: Category) -> str:
    """Walk parent pointers to build a colon-joined path."""
    parts = [cat.name]
    parent = cat.parent
    while parent is not None:
        parts.append(parent.name)
        parent = parent.parent
    return ":".join(reversed(parts))


async def _get_rule_or_404(
    session: AsyncSession, rule_id: int
) -> MemorizedRule:
    rule = await session.get(MemorizedRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


async def _preview_matches(
    session: AsyncSession,
    normalized_payee: str,
    amount_cents: int | None,
) -> RulePreviewResponse:
    """Find transactions whose normalized description contains the normalized
    payee (or vice versa), optionally filtered by exact amount.

    Since the DB is SQLite we cannot replicate normalize_for_matching in SQL.
    We do a broad LIKE pre-filter, then refine with the Python normalizer.
    """
    # Broad SQL pre-filter: description contains the payee text (case-insensitive)
    stmt = select(Transaction).where(
        Transaction.description.isnot(None)
    )

    if amount_cents is not None:
        stmt = stmt.where(Transaction.amount_cents == amount_cents)

    stmt = stmt.order_by(Transaction.posted_at.desc())

    result = await session.execute(stmt)
    all_transactions = result.scalars().all()

    # Refine in Python: normalize each description and check containment
    matches: list[RulePreviewMatch] = []
    for txn in all_transactions:
        normalized_desc = normalize_for_matching(txn.description or "")
        if not normalized_desc:
            continue
        if normalized_payee in normalized_desc or normalized_desc in normalized_payee:
            cat_path = None
            if txn.category:
                cat_path = _category_path(txn.category)
            matches.append(
                RulePreviewMatch(
                    transaction_id=txn.id,
                    description=txn.description,
                    amount_cents=txn.amount_cents,
                    posted_at=txn.posted_at,
                    current_category_path=cat_path,
                )
            )

    return RulePreviewResponse(matches=matches, total_matches=len(matches))


@router.get("", response_model=RuleListResponse)
async def list_rules(
    status: str | None = None,
    search: str | None = None,
    source: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(MemorizedRule)

    if status is not None:
        stmt = stmt.where(MemorizedRule.status == status)
    if source is not None:
        stmt = stmt.where(MemorizedRule.source == source)
    if search is not None:
        normalized_search = normalize_for_matching(search)
        stmt = stmt.where(
            MemorizedRule.normalized_payee.contains(normalized_search)
        )

    stmt = stmt.order_by(MemorizedRule.payee)
    result = await session.execute(stmt)
    rules = list(result.scalars().all())

    return RuleListResponse(rules=rules, total=len(rules))


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: int, session: AsyncSession = Depends(get_session)
):
    return await _get_rule_or_404(session, rule_id)


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    body: RuleCreate, session: AsyncSession = Depends(get_session)
):
    rule = MemorizedRule(
        payee=body.payee,
        normalized_payee=normalize_for_matching(body.payee),
        category_path=body.category_path,
        category_id=body.category_id,
        amount_cents=body.amount_cents,
        kind=body.kind,
        source="user_created",
        status="active",
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    body: RuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    rule = await _get_rule_or_404(session, rule_id)
    updates = body.model_dump(exclude_unset=True)

    for key, value in updates.items():
        setattr(rule, key, value)

    # Recompute normalized_payee when payee changes
    if "payee" in updates:
        rule.normalized_payee = normalize_for_matching(rule.payee)

    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int, session: AsyncSession = Depends(get_session)
):
    rule = await _get_rule_or_404(session, rule_id)
    rule.status = "inactive"
    await session.commit()


@router.post("/preview", response_model=RulePreviewResponse)
async def preview_rule(
    body: RulePreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    normalized = normalize_for_matching(body.payee)
    return await _preview_matches(session, normalized, body.amount_cents)


@router.post("/{rule_id}/preview", response_model=RulePreviewResponse)
async def preview_existing_rule(
    rule_id: int, session: AsyncSession = Depends(get_session)
):
    rule = await _get_rule_or_404(session, rule_id)
    return await _preview_matches(
        session, rule.normalized_payee, rule.amount_cents
    )


@router.post("/generate-drafts", response_model=DraftGenerationResponse)
async def generate_drafts(session: AsyncSession = Depends(get_session)):
    from finance.services.draft_rule_generator import generate_draft_rules

    result = await generate_draft_rules(session)
    return DraftGenerationResponse(
        drafts_created=result.drafts_created,
        skipped_existing=result.skipped_existing,
        conflicts=[
            {"payee": c.payee, "category_ids": c.category_ids, "transaction_count": c.transaction_count}
            for c in result.conflicts
        ],
    )


@router.post("/bulk-activate", response_model=BulkActionResponse)
async def bulk_activate(
    body: BulkActivateRequest,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(MemorizedRule)
        .where(MemorizedRule.id.in_(body.rule_ids))
        .where(MemorizedRule.status == "draft")
    )
    rules = (await session.execute(stmt)).scalars().all()
    for rule in rules:
        rule.status = "active"
    await session.commit()
    return BulkActionResponse(updated=len(rules))


@router.post("/bulk-delete", response_model=BulkActionResponse)
async def bulk_delete(
    body: BulkActivateRequest,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(MemorizedRule)
        .where(MemorizedRule.id.in_(body.rule_ids))
        .where(MemorizedRule.status == "draft")
    )
    rules = (await session.execute(stmt)).scalars().all()
    for rule in rules:
        rule.status = "inactive"
    await session.commit()
    return BulkActionResponse(updated=len(rules))


@router.post("/seed", response_model=RuleSeedResponse)
async def seed_rules(session: AsyncSession = Depends(get_session)):
    from finance.services.seed_rules import import_seed_rules

    result = await import_seed_rules(session)
    return RuleSeedResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        missing_categories=result.missing_categories,
    )


@router.post("/run-monthly", response_model=MonthlyRunResponse)
async def run_monthly(session: AsyncSession = Depends(get_session)):
    """Run all categorization analysis tasks in sequence."""
    from finance.services.draft_rule_generator import generate_draft_rules
    from finance.services.recurrence_detector import detect_recurring
    from finance.services.seed_rules import import_seed_rules

    seed_result = await import_seed_rules(session)
    draft_result = await generate_draft_rules(session)
    recurrence_result = await detect_recurring(session)
    store = await rebuild_rules_index(session, default_embedder())

    return MonthlyRunResponse(
        seed=RuleSeedResponse(
            created=seed_result.created,
            updated=seed_result.updated,
            skipped=seed_result.skipped,
            missing_categories=seed_result.missing_categories,
        ),
        drafts=DraftGenerationResponse(
            drafts_created=draft_result.drafts_created,
            skipped_existing=draft_result.skipped_existing,
            conflicts=[
                {"payee": c.payee, "category_ids": c.category_ids, "transaction_count": c.transaction_count}
                for c in draft_result.conflicts
            ],
        ),
        recurring={
            "groups_found": recurrence_result.groups_found,
            "transactions_flagged": recurrence_result.transactions_flagged,
            "transactions_cleared": recurrence_result.transactions_cleared,
            "by_cadence": recurrence_result.by_cadence,
        },
        reindex=RuleReindexResponse(indexed=len(store)),
    )


@router.post("/reindex", response_model=RuleReindexResponse)
async def reindex_rules(session: AsyncSession = Depends(get_session)):
    store = await rebuild_rules_index(session, default_embedder())
    return RuleReindexResponse(indexed=len(store))
