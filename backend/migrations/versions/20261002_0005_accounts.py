"""accounts: invite-only users, sessions, invites, progress, shelves

Reworks ``users`` (drops ``handle`` and ``progress_json``; adds ``email``,
``password_hash``, ``is_admin``) and adds ``sessions``, ``invites``,
``reading_progress`` and ``library_entries``, plus ``translations.translated_by``.

Legacy ``users`` rows are DELETED: v1 had only a shared demo user with no
email or password, so there is nothing to carry over. The owner account is
created afterwards with ``python -m app.scripts.create_admin``.

Revision ID: 20261002_0005
Revises: 20261002_0004
Create Date: 2026-10-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0005"
down_revision: Union[str, None] = "20261002_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM users")
    op.drop_column("users", "handle")
    op.drop_column("users", "progress_json")
    op.add_column("users", sa.Column("email", sa.String(320), nullable=False))
    op.add_column("users", sa.Column("password_hash", sa.String(256), nullable=False))
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "used_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reading_progress",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chapter_idx", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "library_entries",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "novel_id",
            sa.Integer,
            sa.ForeignKey("novels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("shelf", sa.String(16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.add_column(
        "translations",
        sa.Column(
            "translated_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("translations", "translated_by")
    op.drop_table("library_entries")
    op.drop_table("reading_progress")
    op.drop_table("invites")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.execute("DELETE FROM users")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
    op.add_column(
        "users", sa.Column("progress_json", sa.Text, nullable=False, server_default="{}")
    )
    op.add_column(
        "users", sa.Column("handle", sa.String(64), nullable=False, unique=True)
    )
