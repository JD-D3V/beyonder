"""translated_titles: translated chapter titles and novel title

Revision ID: 20261007_0009
Revises: 20261007_0008
Create Date: 2026-10-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0009"
down_revision: Union[str, None] = "20261007_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("translations", sa.Column("title", sa.String(512), nullable=True))
    op.add_column("novels", sa.Column("title_en", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("novels", "title_en")
    op.drop_column("translations", "title")
