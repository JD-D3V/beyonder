"""invite_used_at: keep invites spent after the invitee is deleted

Revision ID: 20261007_0008
Revises: 20261002_0007
Create Date: 2026-10-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0008"
down_revision: Union[str, None] = "20261002_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invites", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Invites already claimed by a live user are spent.
    op.execute("UPDATE invites SET used_at = now() WHERE used_by IS NOT NULL")


def downgrade() -> None:
    op.drop_column("invites", "used_at")
