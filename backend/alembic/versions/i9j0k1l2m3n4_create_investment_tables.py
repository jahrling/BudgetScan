"""create investment tables

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-09-15 00:00:00.000000

Investment domain per ADR 0006. Money is integer cents; share quantities and
prices are integer millionths (mutual funds carry up to six decimals).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("symbol", sa.String(16), nullable=True),
        sa.Column("cusip", sa.String(9), nullable=True),
        sa.Column("security_type", sa.String(16), nullable=False),
        sa.Column(
            "is_cash_equivalent",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "benchmark_security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_securities_symbol", "securities", ["symbol"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close_micros", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("security_id", "date", name="uq_price_history_security_date"),
    )
    op.create_index("ix_price_history_security_id", "price_history", ["security_id"])
    op.create_index("ix_price_history_date", "price_history", ["date"])

    op.create_table(
        "investment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=True
        ),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("settle_date", sa.Date(), nullable=True),
        sa.Column("quantity_micros", sa.BigInteger(), nullable=True),
        sa.Column("price_micros", sa.BigInteger(), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("fee_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column(
            "linked_transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "external_id", name="uq_invtxn_account_external"),
    )
    op.create_index(
        "ix_investment_transactions_account_id", "investment_transactions", ["account_id"]
    )
    op.create_index(
        "ix_investment_transactions_security_id", "investment_transactions", ["security_id"]
    )
    op.create_index("ix_investment_transactions_action", "investment_transactions", ["action"])
    op.create_index(
        "ix_investment_transactions_trade_date", "investment_transactions", ["trade_date"]
    )
    op.create_index(
        "ix_investment_transactions_linked_transaction_id",
        "investment_transactions",
        ["linked_transaction_id"],
    )

    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("quantity_micros", sa.BigInteger(), nullable=False),
        sa.Column("market_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("price_micros", sa.BigInteger(), nullable=True),
        sa.Column("cost_basis_cents", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "account_id", "security_id", "as_of", name="uq_position_account_security_asof"
        ),
    )
    op.create_index("ix_position_snapshots_account_id", "position_snapshots", ["account_id"])
    op.create_index("ix_position_snapshots_security_id", "position_snapshots", ["security_id"])
    op.create_index("ix_position_snapshots_as_of", "position_snapshots", ["as_of"])

    op.create_table(
        "lots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False
        ),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column(
            "opened_by_txn_id",
            sa.Integer(),
            sa.ForeignKey("investment_transactions.id"),
            nullable=True,
        ),
        sa.Column("quantity_micros_original", sa.BigInteger(), nullable=False),
        sa.Column("quantity_micros_remaining", sa.BigInteger(), nullable=False),
        sa.Column("cost_basis_cents", sa.BigInteger(), nullable=False),
        sa.Column("is_reinvestment", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lots_account_id", "lots", ["account_id"])
    op.create_index("ix_lots_security_id", "lots", ["security_id"])

    op.create_table(
        "lot_disposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("lots.id"), nullable=False),
        sa.Column(
            "sell_txn_id",
            sa.Integer(),
            sa.ForeignKey("investment_transactions.id"),
            nullable=False,
        ),
        sa.Column("quantity_micros", sa.BigInteger(), nullable=False),
        sa.Column("proceeds_cents", sa.BigInteger(), nullable=False),
        sa.Column("basis_cents", sa.BigInteger(), nullable=False),
        sa.Column("realized_gain_cents", sa.BigInteger(), nullable=False),
        sa.Column("term", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lot_disposals_lot_id", "lot_disposals", ["lot_id"])
    op.create_index("ix_lot_disposals_sell_txn_id", "lot_disposals", ["sell_txn_id"])

    op.create_table(
        "investment_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "benchmark_security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id"),
            nullable=True,
        ),
        sa.Column("risk_free_annual_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "default_lot_method", sa.String(16), nullable=False, server_default="fifo"
        ),
        sa.Column(
            "price_fetch_enabled", sa.Boolean(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("investment_settings")
    op.drop_index("ix_lot_disposals_sell_txn_id", table_name="lot_disposals")
    op.drop_index("ix_lot_disposals_lot_id", table_name="lot_disposals")
    op.drop_table("lot_disposals")
    op.drop_index("ix_lots_security_id", table_name="lots")
    op.drop_index("ix_lots_account_id", table_name="lots")
    op.drop_table("lots")
    op.drop_index("ix_position_snapshots_as_of", table_name="position_snapshots")
    op.drop_index("ix_position_snapshots_security_id", table_name="position_snapshots")
    op.drop_index("ix_position_snapshots_account_id", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_index(
        "ix_investment_transactions_linked_transaction_id",
        table_name="investment_transactions",
    )
    op.drop_index(
        "ix_investment_transactions_trade_date", table_name="investment_transactions"
    )
    op.drop_index("ix_investment_transactions_action", table_name="investment_transactions")
    op.drop_index(
        "ix_investment_transactions_security_id", table_name="investment_transactions"
    )
    op.drop_index(
        "ix_investment_transactions_account_id", table_name="investment_transactions"
    )
    op.drop_table("investment_transactions")
    op.drop_index("ix_price_history_date", table_name="price_history")
    op.drop_index("ix_price_history_security_id", table_name="price_history")
    op.drop_table("price_history")
    op.drop_index("ix_securities_symbol", table_name="securities")
    op.drop_table("securities")
