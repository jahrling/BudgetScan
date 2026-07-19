from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AnnotationCreate(BaseModel):
    text: str = Field(..., min_length=1)
    transaction_id: int | None = None


class AnnotationRead(BaseModel):
    id: int
    transaction_id: int | None
    text: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
