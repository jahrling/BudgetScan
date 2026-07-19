from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


class SourceRead(BaseModel):
    source: str
    ref_id: int
    transaction_id: int | None
    text: str
    score: float


class AskResponse(BaseModel):
    route: str
    answer: str
    reason: str
    data: dict = {}
    sources: list[SourceRead] = []


class ReindexResponse(BaseModel):
    indexed: int
