from datetime import datetime

from pydantic import BaseModel


class LineItemCreate(BaseModel):
    transaction_id: int
    category_id: int
    description: str | None = None
    quantity: float | None = None
    unit_price_cents: int | None = None
    amount_cents: int
    ocr_confidence: float | None = None
    user_modified: bool = False


class LineItemRead(BaseModel):
    id: int
    transaction_id: int
    category_id: int
    description: str | None
    quantity: float | None
    unit_price_cents: int | None
    amount_cents: int
    ocr_confidence: float | None
    user_modified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LineItemUpdate(BaseModel):
    category_id: int | None = None
    description: str | None = None
    quantity: float | None = None
    unit_price_cents: int | None = None
    amount_cents: int | None = None
    ocr_confidence: float | None = None
    user_modified: bool | None = None
