from datetime import datetime

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None
    color: str | None = None
    icon: str | None = None


class CategoryRead(BaseModel):
    id: int
    name: str
    parent_id: int | None
    color: str | None
    icon: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    color: str | None = None
    icon: str | None = None
