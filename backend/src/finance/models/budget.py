from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.category import Category


class Budget(Base):
    __tablename__ = "budgets"

    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    period: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    category: Mapped["Category"] = relationship("Category", lazy="selectin")
