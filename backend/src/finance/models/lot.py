from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.investment_transaction import InvestmentTransaction


class Lot(Base):
    """An open or partially closed tax lot.

    ``source="derived"`` rows are a cache rebuilt by replaying the ledger
    (``POST /investments/lots/rebuild``). ``source="statement"`` rows are
    user-entered truth from a broker statement and take precedence for that
    (account, security).

    ``is_reinvestment`` separates the two numbers the section exists to
    separate: ``cost_basis_cents`` (tax basis, sums every lot) versus invested
    capital (sums only lots where this is false).
    """

    __tablename__ = "lots"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    opened_at: Mapped[date] = mapped_column(Date)
    opened_by_txn_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("investment_transactions.id"), nullable=True
    )
    quantity_micros_original: Mapped[int] = mapped_column(BigInteger)
    quantity_micros_remaining: Mapped[int] = mapped_column(BigInteger)
    cost_basis_cents: Mapped[int] = mapped_column(BigInteger)
    is_reinvestment: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), default="derived")

    opened_by: Mapped[Optional["InvestmentTransaction"]] = relationship(
        "InvestmentTransaction", lazy="selectin"
    )
    disposals: Mapped[list["LotDisposal"]] = relationship(
        "LotDisposal", back_populates="lot", cascade="all, delete-orphan", lazy="selectin"
    )


class LotDisposal(Base):
    """Part or all of a lot closed by a sell or shares_out."""

    __tablename__ = "lot_disposals"

    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True)
    sell_txn_id: Mapped[int] = mapped_column(
        ForeignKey("investment_transactions.id"), index=True
    )
    quantity_micros: Mapped[int] = mapped_column(BigInteger)
    proceeds_cents: Mapped[int] = mapped_column(BigInteger)
    basis_cents: Mapped[int] = mapped_column(BigInteger)
    realized_gain_cents: Mapped[int] = mapped_column(BigInteger)
    term: Mapped[str] = mapped_column(String(8))  # short | long

    lot: Mapped["Lot"] = relationship("Lot", back_populates="disposals")
