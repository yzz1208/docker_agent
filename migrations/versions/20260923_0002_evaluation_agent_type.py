"""Add Agent identity to evaluation runs.

Revision ID: 20260923_0002
Revises: 20260921_0001
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0002"
down_revision: str | Sequence[str] | None = "20260921_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("agent_type", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_evaluation_runs_agent_type",
        "evaluation_runs",
        ["agent_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_runs_agent_type",
        table_name="evaluation_runs",
    )
    op.drop_column("evaluation_runs", "agent_type")
