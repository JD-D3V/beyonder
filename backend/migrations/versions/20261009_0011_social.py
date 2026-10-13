"""social: reviews, chapter comments, content reports

Revision ID: 20261009_0011
Revises: 20261009_0010
Create Date: 2026-10-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0011"
down_revision: Union[str, None] = "20261009_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("novel_id", sa.Integer, sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("novel_id", "user_id", name="uq_review_novel_user"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )
    op.create_index("ix_reviews_novel_id", "reviews", ["novel_id"])
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("novel_id", sa.Integer, sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_idx", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted", sa.Boolean, server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_comments_novel_chapter_created", "comments",
        ["novel_id", "chapter_idx", "created_at"],
    )
    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("reporter_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("kind", "target_id", "reporter_id", name="uq_report_once"),
    )


def downgrade() -> None:
    op.drop_table("content_reports")
    op.drop_index("ix_comments_novel_chapter_created", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_reviews_novel_id", table_name="reviews")
    op.drop_table("reviews")
