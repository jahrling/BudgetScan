from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.category import Category


class MemorizedRule(Base):
    __tablename__ = "memorized_rules"

    payee: Mapped[str] = mapped_column(String(512))
    normalized_payee: Mapped[str] = mapped_column(String(512), index=True)
    category_path: Mapped[str] = mapped_column(String(512))
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    amount_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transfer_account: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="payment")
    source: Mapped[str] = mapped_column(String(32), default="qif_import")
    status: Mapped[str] = mapped_column(String(16), default="active")

    category: Mapped[Optional["Category"]] = relationship("Category", lazy="selectin")
