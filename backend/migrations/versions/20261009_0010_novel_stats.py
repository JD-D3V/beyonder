"""novel_stats: per-day view counters for rankings

Revision ID: 20261009_0010
Revises: 20261007_0009
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0010"
down_revision: Union[str, None] = "20261007_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "novel_daily_stats",
        sa.Column(
            "novel_id",
            sa.Integer(),
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("readers", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("novel_daily_stats")
