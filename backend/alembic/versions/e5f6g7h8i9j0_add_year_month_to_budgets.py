"""add year_month to budgets

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("budgets") as batch:
        batch.add_column(
            sa.Column("year_month", sa.String(7), nullable=True)
        )

    # Backfill from start_date (format is YYYY-MM-DD, take first 7 chars)
    budgets = sa.table(
        "budgets",
        sa.column("id", sa.Integer),
        sa.column("start_date", sa.String),
        sa.column("year_month", sa.String),
    )
    op.execute(
        budgets.update().values(
            year_month=sa.func.substr(sa.cast(budgets.c.start_date, sa.String), 1, 7)
        )
    )

    with op.batch_alter_table("budgets") as batch:
        batch.alter_column("year_month", nullable=False)
        batch.create_unique_constraint(
            "uq_budgets_category_month", ["category_id", "year_month"]
        )


def downgrade() -> None:
    with op.batch_alter_table("budgets") as batch:
        batch.drop_constraint("uq_budgets_category_month", type_="unique")
        batch.drop_column("year_month")
