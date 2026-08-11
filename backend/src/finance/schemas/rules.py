from datetime import datetime

from pydantic import BaseModel


class RuleCreate(BaseModel):
    payee: str
    category_path: str
    category_id: int | None = None
    amount_cents: int | None = None
    kind: str = "payment"


class RuleUpdate(BaseModel):
    payee: str | None = None
    category_path: str | None = None
    category_id: int | None = None
    amount_cents: int | None = None
    kind: str | None = None
    status: str | None = None  # "active" | "draft" | "inactive"


class RuleResponse(BaseModel):
    id: int
    payee: str
    normalized_payee: str
    category_path: str
    category_id: int | None
    amount_cents: int | None
    transfer_account: str | None
    kind: str
    source: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuleListResponse(BaseModel):
    rules: list[RuleResponse]
    total: int


class RulePreviewRequest(BaseModel):
    payee: str
    amount_cents: int | None = None


class RulePreviewMatch(BaseModel):
    transaction_id: int
    description: str | None
    amount_cents: int
    posted_at: datetime
    current_category_path: str | None = None


class RulePreviewResponse(BaseModel):
    matches: list[RulePreviewMatch]
    total_matches: int
