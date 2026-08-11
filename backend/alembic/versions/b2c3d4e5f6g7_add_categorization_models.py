"""Add MemorizedRule table and categorization fields to Transaction and Merchant

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": name},
    )
    return result.fetchone() is not None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info('{table}')"))
    return any(row[1] == column for row in result.fetchall())


def upgrade() -> None:
    # -- new table: memorized_rules --
    if not _table_exists("memorized_rules"):
        op.create_table(
            "memorized_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payee", sa.String(512), nullable=False),
            sa.Column("normalized_payee", sa.String(512), nullable=False),
            sa.Column("category_path", sa.String(512), nullable=False),
            sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
            sa.Column("amount_cents", sa.BigInteger(), nullable=True),
            sa.Column("transfer_account", sa.String(256), nullable=True),
            sa.Column("kind", sa.String(32), nullable=False, server_default="payment"),
            sa.Column("source", sa.String(32), nullable=False, server_default="qif_import"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_memorized_rules_normalized_payee", "memorized_rules", ["normalized_payee"])
        op.create_index("ix_memorized_rules_category_id", "memorized_rules", ["category_id"])

    # -- transactions: add categorization columns --
    if not _column_exists("transactions", "category_id"):
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(
                sa.Column(
                    "category_id",
                    sa.Integer(),
                    sa.ForeignKey("categories.id"),
                    nullable=True,
                )
            )
            batch.add_column(
                sa.Column("category_confidence", sa.Float(), nullable=True)
            )
            batch.add_column(
                sa.Column("category_source", sa.String(32), nullable=True)
            )
            batch.add_column(
                sa.Column(
                    "needs_review",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )
            batch.create_index("ix_transactions_category_id", ["category_id"])

    # -- merchants: add resolution columns --
    if not _column_exists("merchants", "resolved_name"):
        with op.batch_alter_table("merchants") as batch:
            batch.add_column(
                sa.Column("resolved_name", sa.String(256), nullable=True)
            )
            batch.add_column(
                sa.Column("resolution_source", sa.String(32), nullable=True)
            )
            batch.add_column(
                sa.Column("resolution_confidence", sa.Float(), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("merchants") as batch:
        batch.drop_column("resolution_confidence")
        batch.drop_column("resolution_source")
        batch.drop_column("resolved_name")

    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_category_id")
        batch.drop_column("needs_review")
        batch.drop_column("category_source")
        batch.drop_column("category_confidence")
        batch.drop_column("category_id")

    op.drop_index("ix_memorized_rules_category_id", table_name="memorized_rules")
    op.drop_index("ix_memorized_rules_normalized_payee", table_name="memorized_rules")
    op.drop_table("memorized_rules")
