"""import_jobs.boot_id: which process owns a running job

Revision ID: 20261012_0017
Revises: 20261011_0016
Create Date: 2026-10-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0017"
down_revision: Union[str, None] = "20261011_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("import_jobs", sa.Column("boot_id", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("import_jobs", "boot_id")
