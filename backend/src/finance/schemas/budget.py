import re
from datetime import date, datetime

from pydantic import BaseModel, field_validator

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_year_month(v: str) -> str:
    if not _MONTH_RE.match(v):
        raise ValueError("year_month must be YYYY-MM format")
    return v


class BudgetCreate(BaseModel):
    category_id: int
    year_month: str
    amount_cents: int
    period: str = "monthly"
    start_date: date | None = None
    end_date: date | None = None
    is_pinned: bool = False

    @field_validator("year_month")
    @classmethod
    def check_year_month(cls, v: str) -> str:
        return _validate_year_month(v)


class BudgetRead(BaseModel):
    id: int
    category_id: int
    year_month: str
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
    year_month: str | None = None
    period: str | None = None
    amount_cents: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_pinned: bool | None = None

    @field_validator("year_month")
    @classmethod
    def check_year_month(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_year_month(v)
        return v


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


class UnbudgetedSpendItem(BaseModel):
    category_id: int | None
    category_name: str
    spent_cents: int
    txn_count: int


class UnbudgetedSpend(BaseModel):
    total_cents: int
    items: list[UnbudgetedSpendItem]


class MonthComparisonItem(BaseModel):
    category_id: int
    category_name: str
    category_icon: str | None = None
    category_color: str | None = None
    current_budgeted_cents: int
    current_spent_cents: int
    prior_spent_cents: int
    prior_budgeted_cents: int


class MonthComparison(BaseModel):
    current_month: str
    prior_month: str
    items: list[MonthComparisonItem]
