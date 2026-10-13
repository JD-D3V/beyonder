"""glossary: locked terms and who added them

Revision ID: 20261002_0006
Revises: 20261002_0005
Create Date: 2026-10-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0006"
down_revision: Union[str, None] = "20261002_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "terms",
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "terms",
        sa.Column(
            "added_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("terms", "added_by")
    op.drop_column("terms", "locked")
