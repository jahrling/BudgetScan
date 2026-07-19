from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.transaction import Transaction


class Annotation(Base):
    """A manual, free-text note the user attaches to a transaction.

    This is the "why did I buy this" prose that structured queries can't
    answer. It is deliberately numbers-free: annotations carry no amounts and
    are the ONLY manual-annotation source the RAG/summarization layer indexes
    (see ADR 0003). Aggregations never read this table.
    """

    __tablename__ = "annotations"

    transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text)

    transaction: Mapped[Optional["Transaction"]] = relationship(
        "Transaction", lazy="selectin"
    )
