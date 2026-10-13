"""display_name: users.display_name (public name for reviews and comments)

Revision ID: 20261009_0014
Revises: 20261009_0013
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0014"
down_revision: Union[str, None] = "20261009_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(24), nullable=True))
    op.create_unique_constraint("uq_users_display_name", "users", ["display_name"])
    op.create_check_constraint(
        "ck_users_display_name",
        "users",
        "display_name IS NULL OR display_name ~ '^[A-Za-z0-9_-]{3,24}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_display_name", "users", type_="check")
    op.drop_constraint("uq_users_display_name", "users", type_="unique")
    op.drop_column("users", "display_name")
