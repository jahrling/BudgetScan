"""add transfer_target_account_id to transactions

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: str | None = "j0k1l2m3n4o5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(
            sa.Column("transfer_target_account_id", sa.Integer(), nullable=True)
        )
        batch.create_index(
            "ix_transactions_transfer_target_account_id",
            ["transfer_target_account_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_transfer_target_account_id")
        batch.drop_column("transfer_target_account_id")
