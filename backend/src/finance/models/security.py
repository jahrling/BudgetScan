from datetime import date
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base


SECURITY_TYPES: frozenset[str] = frozenset(
    {"stock", "etf", "mutual_fund", "bond", "cash", "index", "other"}
)


class Security(Base):
    """A tradable instrument, or a benchmark index, or a cash-equivalent sweep.

    ``name`` is the identity Quicken uses in ``!Type:Invst`` records (the ``Y``
    line), so it is unique. ``symbol`` is the ticker where one exists; Quicken
    exports some broker-feed pseudo-securities (money-market sweeps, pending
    distributions) with no symbol at all.
    """

    __tablename__ = "securities"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    cusip: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    security_type: Mapped[str] = mapped_column(String(16), default="other")
    # Money-market sweep / settlement-fund pseudo-securities move cash around
    # but are not holdings. They are excluded from positions and lots.
    is_cash_equivalent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    # Per-holding benchmark override (e.g. AGG for a bond ETF). Null means use
    # InvestmentSettings.benchmark_security_id.
    benchmark_security_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("securities.id"), nullable=True
    )

    benchmark: Mapped[Optional["Security"]] = relationship(
        "Security", remote_side="Security.id", lazy="selectin"
    )


class PriceHistory(Base):
    """One closing price per security per calendar day. ``close_micros`` is
    dollars × 1,000,000."""

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uq_price_history_security_date"),
    )

    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    close_micros: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(16), default="manual")

    security: Mapped["Security"] = relationship("Security", lazy="selectin")
