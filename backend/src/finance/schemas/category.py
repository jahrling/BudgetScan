from datetime import datetime

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None
    color: str | None = None
    icon: str | None = None
    is_income: bool = False


class CategoryRead(BaseModel):
    id: int
    name: str
    parent_id: int | None
    color: str | None
    icon: str | None
    is_income: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    color: str | None = None
    icon: str | None = None
    is_income: bool | None = None
