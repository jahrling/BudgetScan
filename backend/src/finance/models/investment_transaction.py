from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance.models.base import Base

if TYPE_CHECKING:
    from finance.models.account import Account
    from finance.models.security import Security
    from finance.models.transaction import Transaction


INVESTMENT_ACTIONS: frozenset[str] = frozenset(
    {
        "buy",
        "sell",
        "dividend",
        "reinvest_dividend",
        "capital_gain_dist",
        "reinvest_capital_gain",
        "interest",
        "fee",
        "shares_in",
        "shares_out",
        "cash_in",
        "cash_out",
        "split",
        "return_of_capital",
        "other",
    }
)

# Actions that open a lot. reinvest_* lots are flagged is_reinvestment so
# invested capital (external money) can be separated from cost basis.
LOT_OPENING_ACTIONS: frozenset[str] = frozenset(
    {"buy", "reinvest_dividend", "reinvest_capital_gain", "shares_in"}
)
LOT_CLOSING_ACTIONS: frozenset[str] = frozenset({"sell", "shares_out"})
# Income received, whether paid to cash or reinvested.
INCOME_ACTIONS: frozenset[str] = frozenset(
    {"dividend", "reinvest_dividend", "capital_gain_dist", "reinvest_capital_gain", "interest"}
)


class InvestmentTransaction(Base):
    """One ledger event in an investment account (ADR 0006).

    ``amount_cents`` is the signed cash effect on the account: negative when
    cash leaves (buy, fee, cash_out), positive when it arrives (sell, dividend,
    cash_in). ``reinvest_*`` actions net to zero cash but carry the reinvested
    amount here so income can still be summed. ``shares_in``/``shares_out``/
    ``split`` have no cash effect and store 0.

    ``quantity_micros`` and ``price_micros`` are shares × 1e6 and dollars × 1e6.
    ``amount_cents`` is authoritative; quantity × price is display-only.
    """

    __tablename__ = "investment_transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_invtxn_account_external"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    security_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("securities.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(24), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    settle_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    quantity_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    price_micros: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(16), default="manual")
    # OFX FITID, or a content hash for QIF (which has no ids). Unique per account.
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Bank-side Transaction when a cash transfer crosses the boundary.
    linked_transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )
    memo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    security: Mapped[Optional["Security"]] = relationship("Security", lazy="selectin")
    linked_transaction: Mapped[Optional["Transaction"]] = relationship(
        "Transaction", lazy="selectin"
    )
