from datetime import datetime

from pydantic import BaseModel, Field


class SplitCandidateSchema(BaseModel):
    category_path: str
    amount_cents: int
    description: str | None = None


class TransactionCandidateSchema(BaseModel):
    source_account_key: str
    account_id: int | None
    posted_at: datetime
    amount_cents: int
    description: str | None
    quicken_id: str | None
    currency: str | None = None
    splits: list[SplitCandidateSchema] = Field(default_factory=list)
    match_status: str = "new"
    match_transaction_id: int | None = None


class ParseResultSchema(BaseModel):
    candidates: list[TransactionCandidateSchema]
    unmapped_accounts: list[str]
    errors: list[str]


class ConfirmAction(BaseModel):
    candidate_index: int
    action: str  # 'create' | 'skip' | 'merge-with:<id>'


class ConfirmRequest(BaseModel):
    candidates: list[TransactionCandidateSchema]
    actions: list[ConfirmAction]
    create_missing_categories: bool = False


class ConfirmResponse(BaseModel):
    created_ids: list[int]
    merged_ids: list[int]
    skipped: int
    errors: list[str]
