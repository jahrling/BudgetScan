"""add recurring transaction fields

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("is_recurring", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("recurrence_cadence", sa.String(16), nullable=True))
        batch.add_column(
            sa.Column("recurrence_group_id", sa.Integer(), nullable=True, index=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("recurrence_group_id")
        batch.drop_column("recurrence_cadence")
        batch.drop_column("is_recurring")
