from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.account import Account
    from finance.models.category import Category
    from finance.models.merchant import Merchant
    from finance.models.receipt import Receipt


class Transaction(Base):
    __tablename__ = "transactions"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    merchant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("merchants.id"), nullable=True
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quicken_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("receipts.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    category_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    category_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    needs_review: Mapped[bool] = mapped_column(default=True)

    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    category: Mapped[Optional["Category"]] = relationship("Category", lazy="selectin")
    merchant: Mapped[Optional["Merchant"]] = relationship("Merchant", lazy="selectin")
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt", lazy="selectin")
