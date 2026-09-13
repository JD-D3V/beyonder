"""resumable translation progress

Adds ``pieces_done`` to translations so a long chapter can be translated over
several short requests instead of one that times out. NULL means complete, so
every existing row stays valid without a data backfill.

Revision ID: 20260912_0003
Revises: 20260912_0002
Create Date: 2026-09-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0003"
down_revision: Union[str, None] = "20260912_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "translations", sa.Column("pieces_done", sa.Integer, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("translations", "pieces_done")
