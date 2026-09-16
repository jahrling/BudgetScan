from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.security import Security


LOT_METHODS: frozenset[str] = frozenset({"fifo", "average", "specific"})


class InvestmentSettings(Base):
    """Singleton row (id == 1). Plan §9.3 D5-D7 set the defaults."""

    __tablename__ = "investment_settings"

    benchmark_security_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("securities.id"), nullable=True
    )
    risk_free_annual_bps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    default_lot_method: Mapped[str] = mapped_column(
        String(16), default="fifo", server_default="fifo"
    )
    price_fetch_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    benchmark: Mapped[Optional["Security"]] = relationship("Security", lazy="selectin")
