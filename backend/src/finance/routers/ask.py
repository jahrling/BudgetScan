"""HTTP surface for the finance summarization/RAG layer.

Mounted on the existing FastAPI app, which is bound to 127.0.0.1 — this adds no
new port or external binding (see ADR 0005). Routing between SQL and vector
retrieval happens in `finance_qa.answer`; this router is a thin adapter.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.db import get_session
from finance.schemas.ask import AskRequest, AskResponse, ReindexResponse, SourceRead
from finance.services import finance_qa, vector_store
from finance.services.embeddings import default_embedder

router = APIRouter(
    prefix="/api/ask",
    tags=["ask"],
    dependencies=[Depends(current_user)],
)


@router.post("", response_model=AskResponse)
async def ask(data: AskRequest, session: AsyncSession = Depends(get_session)):
    result = await finance_qa.answer(session, data.query)
    return AskResponse(
        route=result.route.value,
        answer=result.text,
        reason=result.reason,
        data=result.data,
        sources=[
            SourceRead(
                source=h.source,
                ref_id=h.ref_id,
                transaction_id=h.transaction_id,
                text=h.text,
                score=h.score,
            )
            for h in result.sources
        ],
    )


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(session: AsyncSession = Depends(get_session)):
    """Rebuild the local vector index from current annotations + line items."""
    store = await vector_store.rebuild_from_db(session, default_embedder())
    return ReindexResponse(indexed=len(store))
