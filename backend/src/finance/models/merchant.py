from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.category import Category


class Merchant(Base):
    __tablename__ = "merchants"

    name: Mapped[str] = mapped_column(String(256))
    normalized_name: Mapped[str] = mapped_column(String(256), index=True)
    default_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    default_category: Mapped[Optional["Category"]] = relationship("Category", lazy="selectin")
