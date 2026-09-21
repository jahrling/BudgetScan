"""add account_number to accounts

Revision ID: d3e5f7a8b9c0
Revises: ce41d7beedb9
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e5f7a8b9c0'
down_revision: Union[str, None] = 'ce41d7beedb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('account_number', sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'account_number')
