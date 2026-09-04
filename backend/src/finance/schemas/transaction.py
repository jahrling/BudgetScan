from datetime import datetime

from pydantic import BaseModel, field_validator

from finance.schemas.line_item import LineItemCreate, LineItemRead


class TransactionCreate(BaseModel):
    account_id: int
    merchant_id: int | None = None
    posted_at: datetime
    amount_cents: int
    description: str | None = None
    quicken_id: str | None = None
    receipt_id: int | None = None
    status: str = "pending"
    line_items: list[LineItemCreate] | None = None


class TransactionRead(BaseModel):
    id: int
    account_id: int
    merchant_id: int | None
    posted_at: datetime
    amount_cents: int
    description: str | None
    quicken_id: str | None
    receipt_id: int | None
    status: str
    transfer_pair_id: int | None = None
    category_id: int | None = None
    category_source: str | None = None
    category_confidence: float | None = None
    needs_review: bool = True
    excluded: bool | None = None
    created_at: datetime
    updated_at: datetime
    merchant_name: str | None = None
    account_name: str | None = None
    category_name: str | None = None
    transfer_account_name: str | None = None

    model_config = {"from_attributes": True}


class TransactionDetail(TransactionRead):
    line_items: list[LineItemRead] = []


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    merchant_id: int | None = None
    posted_at: datetime | None = None
    description: str | None = None
    quicken_id: str | None = None
    receipt_id: int | None = None
    status: str | None = None
    excluded: bool | None = None

    @field_validator("excluded", mode="before")
    @classmethod
    def coerce_false_to_none(cls, v: object) -> bool | None:
        if v is False:
            return None
        return v  # type: ignore[return-value]


class TransactionListParams(BaseModel):
    offset: int = 0
    limit: int = 50
    date_from: datetime | None = None
    date_to: datetime | None = None
    account_id: int | None = None
    status: str | None = None
    category_id: int | None = None
    excluded: str | None = None
