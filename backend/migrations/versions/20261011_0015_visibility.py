"""visibility: private books (novels.visibility, novels.owner_id)

Revision ID: 20261011_0015
Revises: 20261009_0014
Create Date: 2026-10-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0015"
down_revision: Union[str, None] = "20261009_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing books stay public and ownerless.
    op.add_column(
        "novels",
        sa.Column(
            "visibility", sa.String(16), nullable=False, server_default="public"
        ),
    )
    op.add_column("novels", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_novels_owner_id_users", "novels", "users", ["owner_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_novels_owner_id", "novels", ["owner_id"])
    op.create_check_constraint(
        "ck_novels_visibility", "novels", "visibility IN ('public', 'private')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_novels_visibility", "novels", type_="check")
    op.drop_index("ix_novels_owner_id", table_name="novels")
    op.drop_constraint("fk_novels_owner_id_users", "novels", type_="foreignkey")
    op.drop_column("novels", "owner_id")
    op.drop_column("novels", "visibility")
