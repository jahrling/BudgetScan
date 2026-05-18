from datetime import datetime

from pydantic import BaseModel


class TransactionCreate(BaseModel):
    account_id: int
    merchant_id: int | None = None
    posted_at: datetime
    amount_cents: int
    description: str | None = None
    quicken_id: str | None = None
    receipt_id: int | None = None
    status: str = "pending"


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

    model_config = {"from_attributes": True}


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    merchant_id: int | None = None
    posted_at: datetime | None = None
    amount_cents: int | None = None
    description: str | None = None
    quicken_id: str | None = None
    receipt_id: int | None = None
    status: str | None = None
