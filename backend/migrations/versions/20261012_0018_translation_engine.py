"""translations.engine ('ai'|'mt'), novels.author_en/description_en, mt_jobs

Machine translation jobs live in their own table (not import_jobs) so the
per-user import caps and the /imports listing are untouched.

Revision ID: 20261012_0018
Revises: 20261012_0017
Create Date: 2026-10-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0018"
down_revision: Union[str, None] = "20261012_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "translations",
        sa.Column("engine", sa.String(8), nullable=False, server_default="ai"),
    )
    op.create_check_constraint(
        "ck_translations_engine", "translations", "engine IN ('ai', 'mt')"
    )
    op.drop_constraint("uq_translation_chap_lang", "translations", type_="unique")
    op.create_unique_constraint(
        "uq_translation_chap_lang_engine", "translations",
        ["chapter_id", "target_lang", "engine"],
    )
    op.add_column("novels", sa.Column("author_en", sa.String(256), nullable=True))
    op.add_column("novels", sa.Column("description_en", sa.Text(), nullable=True))
    op.create_table(
        "mt_jobs",
        sa.Column(
            "novel_id", sa.Integer(),
            sa.ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("boot_id", sa.String(32), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_mt_jobs_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("mt_jobs")
    op.drop_column("novels", "description_en")
    op.drop_column("novels", "author_en")
    op.execute("DELETE FROM translations WHERE engine = 'mt'")
    op.drop_constraint("uq_translation_chap_lang_engine", "translations", type_="unique")
    op.create_unique_constraint(
        "uq_translation_chap_lang", "translations", ["chapter_id", "target_lang"]
    )
    op.drop_constraint("ck_translations_engine", "translations", type_="check")
    op.drop_column("translations", "engine")
