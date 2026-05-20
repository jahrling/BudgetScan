"""add dropbox_path to receipts

Revision ID: 9b3c4d5e6f70
Revises: 7a1c9b2d3e4f
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b3c4d5e6f70"
down_revision: Union[str, None] = "7a1c9b2d3e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("dropbox_path", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.drop_column("dropbox_path")
