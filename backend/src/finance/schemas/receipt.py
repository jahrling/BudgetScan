from datetime import datetime

from pydantic import BaseModel


class ReceiptCreate(BaseModel):
    file_path: str
    original_filename: str
    sha256: str
    captured_at: datetime
    ocr_model: str | None = None
    ocr_status: str = "pending"


class ReceiptRead(BaseModel):
    id: int
    file_path: str
    original_filename: str
    sha256: str
    captured_at: datetime
    ocr_raw_json: str | None
    ocr_model: str | None
    ocr_status: str
    ocr_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReceiptUpdate(BaseModel):
    ocr_raw_json: str | None = None
    ocr_model: str | None = None
    ocr_status: str | None = None
    ocr_error: str | None = None


class ToTransactionRequest(BaseModel):
    account_id: int
    merchant_id: int | None = None
