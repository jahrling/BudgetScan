from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.category import Category
    from finance.models.transaction import Transaction


class LineItem(Base):
    __tablename__ = "line_items"

    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_modified: Mapped[bool] = mapped_column(Boolean, default=False)

    transaction: Mapped["Transaction"] = relationship("Transaction", lazy="selectin")
    category: Mapped["Category"] = relationship("Category", lazy="selectin")
