from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finance.models.base import Base


class Receipt(Base):
    __tablename__ = "receipts"

    file_path: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ocr_raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending")
    ocr_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
