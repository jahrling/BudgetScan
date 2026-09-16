from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.account import Account
    from finance.models.security import Security


class PositionSnapshot(Base):
    """A holding's quantity and value as of a date — from a statement, an OFX
    ``INVPOSLIST``, or manual entry. These are the valuation points that
    time-weighted return is chain-linked across (plan §3.3)."""

    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "security_id", "as_of", name="uq_position_account_security_asof"
        ),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    quantity_micros: Mapped[int] = mapped_column(BigInteger)
    market_value_cents: Mapped[int] = mapped_column(BigInteger)
    price_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cost_basis_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")

    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    security: Mapped["Security"] = relationship("Security", lazy="selectin")
