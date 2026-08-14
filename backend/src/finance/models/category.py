from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.category import Category as SelfRef


class Category(Base):
    __tablename__ = "categories"

    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_income: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    parent: Mapped[Optional["SelfRef"]] = relationship(
        "Category", remote_side="Category.id", back_populates="children", lazy="selectin"
    )
    children: Mapped[list["SelfRef"]] = relationship(
        "Category", back_populates="parent", lazy="selectin"
    )
