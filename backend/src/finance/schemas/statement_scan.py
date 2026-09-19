from datetime import date, datetime

from pydantic import BaseModel


class StatementScanRead(BaseModel):
    id: int
    file_path: str
    original_filename: str
    sha256: str
    account_id: int | None
    as_of: date | None
    ocr_status: str
    ocr_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StatementReviewPosition(BaseModel):
    symbol: str | None = None
    name: str
    quantity_micros: int
    price_micros: int | None = None
    market_value_cents: int
    cost_basis_cents: int | None = None
    matched_security_id: int | None = None
    matched_security_name: str | None = None


class StatementReviewPreview(BaseModel):
    account_name: str | None = None
    statement_date: str | None = None
    positions: list[StatementReviewPosition]


class MaterializePosition(BaseModel):
    security_id: int | None = None
    symbol: str | None = None
    name: str
    quantity_micros: int
    market_value_cents: int
    price_micros: int | None = None
    cost_basis_cents: int | None = None


class MaterializeRequest(BaseModel):
    account_id: int
    as_of: date
    positions: list[MaterializePosition]
