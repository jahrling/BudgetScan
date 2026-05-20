from datetime import datetime

from pydantic import BaseModel

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
    created_at: datetime
    updated_at: datetime
    merchant_name: str | None = None

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


class TransactionListParams(BaseModel):
    offset: int = 0
    limit: int = 50
    date_from: datetime | None = None
    date_to: datetime | None = None
    account_id: int | None = None
    status: str | None = None
    category_id: int | None = None
