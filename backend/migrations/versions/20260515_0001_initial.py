"""initial schema

Revision ID: 20260515_0001
Revises:
Create Date: 2026-05-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260515_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "novels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_lang", sa.String(8), nullable=False, server_default="zh"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("novel_id", "idx", name="uq_chapter_novel_idx"),
    )
    op.create_index("ix_chapter_novel_idx", "chapters", ["novel_id", "idx"])

    op.create_table(
        "translations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "chapter_id",
            sa.Integer,
            sa.ForeignKey("chapters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_lang", sa.String(8), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("critic_passes", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("chapter_id", "target_lang", name="uq_translation_chap_lang"),
    )

    op.create_table(
        "terms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_term", sa.String(256), nullable=False),
        sa.Column("target_term", sa.String(256), nullable=False),
        sa.Column("target_lang", sa.String(8), nullable=False, server_default="en"),
        sa.Column("kind", sa.String(32), nullable=False, server_default="other"),
        sa.Column("first_chapter", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "novel_id", "source_term", "target_lang", name="uq_term_novel_src_lang"
        ),
    )
    op.create_index("ix_term_novel", "terms", ["novel_id"])

    op.create_table(
        "relations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("src_term", sa.String(256), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("dst_term", sa.String(256), nullable=False),
        sa.Column("first_chapter", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
    )
    op.create_index("ix_relation_novel_chap", "relations", ["novel_id", "first_chapter"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("handle", sa.String(64), nullable=False, unique=True),
        sa.Column("progress_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_index("ix_relation_novel_chap", table_name="relations")
    op.drop_table("relations")
    op.drop_index("ix_term_novel", table_name="terms")
    op.drop_table("terms")
    op.drop_table("translations")
    op.drop_index("ix_chapter_novel_idx", table_name="chapters")
    op.drop_table("chapters")
    op.drop_table("novels")
