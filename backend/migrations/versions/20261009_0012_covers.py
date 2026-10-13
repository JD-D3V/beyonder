"""covers: novel_covers table

Revision ID: 20261009_0012
Revises: 20261009_0011
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0012"
down_revision: Union[str, None] = "20261009_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "novel_covers",
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("novel_covers")
