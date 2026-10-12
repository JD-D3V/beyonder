"""import_jobs: background table-of-contents imports

Revision ID: 20261011_0016
Revises: 20261011_0015
Create Date: 2026-10-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0016"
down_revision: Union[str, None] = "20261011_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "novel_id", sa.Integer(),
            sa.ForeignKey("novels.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_import_jobs_status",
        ),
    )
    op.create_index("ix_import_jobs_user_id", "import_jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_user_id", table_name="import_jobs")
    op.drop_table("import_jobs")
