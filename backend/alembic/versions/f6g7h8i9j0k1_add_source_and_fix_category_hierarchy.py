"""add source column and fix category hierarchy

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-09-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch:
        batch.add_column(
            sa.Column(
                "source",
                sa.String(16),
                nullable=False,
                server_default="quicken",
            )
        )

    conn = op.get_bind()

    # Mark categories that were created in the app (have parent_id set,
    # no colon in name) as source="app"
    conn.execute(
        sa.text(
            "UPDATE categories SET source = 'app' "
            "WHERE parent_id IS NOT NULL AND name NOT LIKE '%:%'"
        )
    )

    # Fix colon categories: split "Parent:Child", find the parent row,
    # set parent_id, rename to just the child part
    rows = conn.execute(
        sa.text("SELECT id, name FROM categories WHERE name LIKE '%:%'")
    ).fetchall()

    # Build a lookup of existing parent categories by name
    parents = conn.execute(
        sa.text("SELECT id, name FROM categories WHERE name NOT LIKE '%:%'")
    ).fetchall()
    parent_by_name = {r[1]: r[0] for r in parents}

    for cat_id, name in rows:
        parts = name.split(":", 1)
        if len(parts) != 2:
            continue
        parent_name = parts[0].strip()
        child_name = parts[1].strip()

        parent_id = parent_by_name.get(parent_name)
        if parent_id is None:
            continue

        conn.execute(
            sa.text(
                "UPDATE categories SET name = :name, parent_id = :pid "
                "WHERE id = :id"
            ),
            {"name": child_name, "pid": parent_id, "id": cat_id},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Restore colon names for categories that have a quicken-sourced parent
    rows = conn.execute(
        sa.text(
            "SELECT c.id, c.name, p.name "
            "FROM categories c "
            "JOIN categories p ON c.parent_id = p.id "
            "WHERE c.source = 'quicken' AND c.parent_id IS NOT NULL"
        )
    ).fetchall()

    for cat_id, child_name, parent_name in rows:
        conn.execute(
            sa.text(
                "UPDATE categories SET name = :name, parent_id = NULL "
                "WHERE id = :id"
            ),
            {"name": f"{parent_name}:{child_name}", "id": cat_id},
        )

    with op.batch_alter_table("categories") as batch:
        batch.drop_column("source")
