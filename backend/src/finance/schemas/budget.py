from datetime import date, datetime

from pydantic import BaseModel


class BudgetCreate(BaseModel):
    category_id: int
    period: str
    amount_cents: int
    start_date: date
    end_date: date | None = None
    is_pinned: bool = False


class BudgetRead(BaseModel):
    id: int
    category_id: int
    period: str
    amount_cents: int
    start_date: date
    end_date: date | None
    is_pinned: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetUpdate(BaseModel):
    category_id: int | None = None
    period: str | None = None
    amount_cents: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_pinned: bool | None = None


class BudgetStatusItem(BaseModel):
    budget_id: int
    category_id: int
    category_name: str
    category_icon: str | None = None
    category_color: str | None = None
    budgeted_cents: int
    spent_cents: int
    remaining_cents: int
    percent_used: float
    percent_remaining: float
    is_pinned: bool
    period: str
    period_start: date
    period_end: date
    days_remaining: int


class IncomeCategoryItem(BaseModel):
    category_id: int
    category_name: str
    category_icon: str | None = None
    category_color: str | None = None
    amount_cents: int
    txn_count: int


class IncomeSummary(BaseModel):
    total_cents: int
    categories: list[IncomeCategoryItem]
