from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finance.models.base import Base


class StatementScan(Base):
    __tablename__ = "statement_scans"

    file_path: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ocr_raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending")
    ocr_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
