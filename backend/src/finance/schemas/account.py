from datetime import datetime

from pydantic import BaseModel


class AccountCreate(BaseModel):
    name: str
    type: str
    quicken_id: str | None = None
    currency: str = "USD"


class AccountRead(BaseModel):
    id: int
    name: str
    type: str
    quicken_id: str | None
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    quicken_id: str | None = None
    currency: str | None = None
