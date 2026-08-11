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
    cleared: str | None = None
    transfer_account: str | None = None
    match_status: str = "new"
    match_transaction_id: int | None = None
    match_description: str | None = None
    match_amount_cents: int | None = None
    match_posted_at: datetime | None = None
    match_category_path: str | None = None


class CategoryDefinitionSchema(BaseModel):
    name: str
    description: str | None = None
    is_income: bool = False
    tax_related: bool = False
    tax_schedule: str | None = None


class MemorizedRuleSchema(BaseModel):
    payee: str
    category_path: str
    amount_cents: int | None = None
    transfer_account: str | None = None
    kind: str = "payment"


class RuleConflictSchema(BaseModel):
    incoming_payee: str
    incoming_category_path: str
    existing_rule_id: int
    existing_category_path: str
    existing_match_count: int = 0


class RulePersistResultSchema(BaseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: list[RuleConflictSchema] = Field(default_factory=list)


class ParseResultSchema(BaseModel):
    candidates: list[TransactionCandidateSchema]
    unmapped_accounts: list[str]
    errors: list[str]
    categories: list[CategoryDefinitionSchema] = Field(default_factory=list)
    memorized_rules: list[MemorizedRuleSchema] = Field(default_factory=list)
    rule_persist_result: RulePersistResultSchema | None = None


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
    overwritten_ids: list[int] = Field(default_factory=list)
    skipped: int
    errors: list[str]
