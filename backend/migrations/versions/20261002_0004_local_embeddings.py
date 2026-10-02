"""local embeddings: terms.embedding becomes 384-dim

Switches from Gemini (768-dim) to a local fastembed model (384-dim). Old
vectors are meaningless in the new space, so the column is dropped and
re-added empty; ``python -m app.scripts.reembed`` rebuilds Qdrant, and term
embeddings are refilled as terms are next written.

Revision ID: 20261002_0004
Revises: 20260912_0003
Create Date: 2026-10-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20261002_0004"
down_revision: Union[str, None] = "20260912_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("terms", "embedding")
    op.add_column("terms", sa.Column("embedding", Vector(384), nullable=True))


def downgrade() -> None:
    op.drop_column("terms", "embedding")
    op.add_column("terms", sa.Column("embedding", Vector(768), nullable=True))
