from datetime import date, datetime

from pydantic import BaseModel


class BudgetCreate(BaseModel):
    category_id: int
    period: str
    amount_cents: int
    start_date: date
    end_date: date | None = None


class BudgetRead(BaseModel):
    id: int
    category_id: int
    period: str
    amount_cents: int
    start_date: date
    end_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetUpdate(BaseModel):
    category_id: int | None = None
    period: str | None = None
    amount_cents: int | None = None
    start_date: date | None = None
    end_date: date | None = None


class BudgetStatusItem(BaseModel):
    category_id: int
    category_name: str
    budgeted_cents: int
    spent_cents: int
    remaining_cents: int
    percent_used: float
