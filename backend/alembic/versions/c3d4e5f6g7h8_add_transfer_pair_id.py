"""Add transfer_pair_id to transactions

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6g7h8"
down_revision: Union[str, None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(f"PRAGMA table_info('{table}')"))
    return any(row[1] == column for row in result.fetchall())


def upgrade() -> None:
    if not _column_exists("transactions", "transfer_pair_id"):
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(
                sa.Column("transfer_pair_id", sa.Integer(), nullable=True)
            )
            batch.create_index("ix_transactions_transfer_pair_id", ["transfer_pair_id"])


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_transfer_pair_id")
        batch.drop_column("transfer_pair_id")
