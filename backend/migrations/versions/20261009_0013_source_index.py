"""source_index: novels.source_index_url, chapters.source_url

Revision ID: 20261009_0013
Revises: 20261009_0012
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0013"
down_revision: Union[str, None] = "20261009_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("novels", sa.Column("source_index_url", sa.String(1024), nullable=True))
    op.add_column("chapters", sa.Column("source_url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("chapters", "source_url")
    op.drop_column("novels", "source_index_url")
