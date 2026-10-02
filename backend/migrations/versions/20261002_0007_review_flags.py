"""review_flags: non-blocking QA queue

Revision ID: 20261002_0007
Revises: 20261002_0006
Create Date: 2026-10-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0007"
down_revision: Union[str, None] = "20261002_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_flags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "novel_id", sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("chapter_idx", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_span", sa.Text, nullable=False, server_default=""),
        sa.Column("target_span", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "resolved_by", sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.create_index(
        "ix_review_flags_novel_status_chapter",
        "review_flags", ["novel_id", "status", "chapter_idx"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_flags_novel_status_chapter", table_name="review_flags")
    op.drop_table("review_flags")
