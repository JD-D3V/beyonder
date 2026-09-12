"""library metadata on novels

Adds the fields a library view needs: who wrote it, what it is about, how to
group it, and whether it is finished. Everything is nullable so existing rows
stay valid.

Revision ID: 20260912_0002
Revises: 20260515_0001
Create Date: 2026-09-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0002"
down_revision: Union[str, None] = "20260515_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("novels", sa.Column("author", sa.String(256), nullable=True))
    op.add_column("novels", sa.Column("description", sa.Text, nullable=True))
    # Comma-separated, lowercased. A join table is overkill for a personal
    # library and makes the common "show me the tags" query a second round trip.
    op.add_column("novels", sa.Column("tags", sa.String(512), nullable=True))
    op.add_column(
        "novels",
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="ongoing"
        ),
    )
    op.add_column(
        "novels",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_novel_updated_at", "novels", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_novel_updated_at", table_name="novels")
    for col in ("updated_at", "status", "tags", "description", "author"):
        op.drop_column("novels", col)
