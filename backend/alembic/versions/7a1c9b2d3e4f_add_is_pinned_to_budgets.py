"""add is_pinned to budgets

Revision ID: 7a1c9b2d3e4f
Revises: 3ffd65ac28b1
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a1c9b2d3e4f"
down_revision: Union[str, None] = "3ffd65ac28b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("budgets") as batch:
        batch.add_column(
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("budgets") as batch:
        batch.drop_column("is_pinned")
