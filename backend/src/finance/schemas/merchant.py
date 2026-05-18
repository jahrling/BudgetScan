from datetime import datetime

from pydantic import BaseModel


class MerchantCreate(BaseModel):
    name: str
    normalized_name: str
    default_category_id: int | None = None
    notes: str | None = None


class MerchantRead(BaseModel):
    id: int
    name: str
    normalized_name: str
    default_category_id: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MerchantUpdate(BaseModel):
    name: str | None = None
    normalized_name: str | None = None
    default_category_id: int | None = None
    notes: str | None = None
