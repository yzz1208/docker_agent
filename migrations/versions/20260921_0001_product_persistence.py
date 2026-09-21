"""Create product persistence schema.

Revision ID: 20260921_0001
Revises:
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260921_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_configurations",
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("model_settings", sa.JSON(), nullable=False),
        sa.Column("retrieval_settings", sa.JSON(), nullable=False),
        sa.Column("runtime_settings", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("agent_type"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_agent_type",
        "conversations",
        ["agent_type"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=True),
        sa.Column("use_docs", sa.Boolean(), nullable=True),
        sa.Column("clarification", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_id",
        "messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_messages_created_at",
        "messages",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_messages_role",
        "messages",
        ["role"],
        unique=False,
    )

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("planned_workers", sa.JSON(), nullable=False),
        sa.Column("completed_workers", sa.JSON(), nullable=False),
        sa.Column("worker_trace", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_executions_message_id",
        "agent_executions",
        ["message_id"],
        unique=True,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=True),
        sa.Column("use_docs", sa.Boolean(), nullable=True),
        sa.Column("planned_workers", sa.JSON(), nullable=False),
        sa.Column("completed_workers", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_agent_type",
        "agent_runs",
        ["agent_type"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_completed_at",
        "agent_runs",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_conversation_id",
        "agent_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_error_type",
        "agent_runs",
        ["error_type"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_route",
        "agent_runs",
        ["route"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_started_at",
        "agent_runs",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status",
        "agent_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("suite", sa.String(length=64), nullable=False),
        sa.Column("dataset_name", sa.String(length=240), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("git_revision", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("aggregate_metrics", sa.JSON(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_completed_at",
        "evaluation_runs",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_dataset_version",
        "evaluation_runs",
        ["dataset_version"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_error_type",
        "evaluation_runs",
        ["error_type"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_git_revision",
        "evaluation_runs",
        ["git_revision"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_started_at",
        "evaluation_runs",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_status",
        "evaluation_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_suite",
        "evaluation_runs",
        ["suite"],
        unique=False,
    )

    op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "evaluation_run_id",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("case_key", sa.String(length=240), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=True),
        sa.Column("repeat", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "case_key",
            name="uq_evaluation_case_run_key",
        ),
    )
    op.create_index(
        "ix_evaluation_case_results_case_id",
        "evaluation_case_results",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_case_results_created_at",
        "evaluation_case_results",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_case_results_evaluation_run_id",
        "evaluation_case_results",
        ["evaluation_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_case_results_status",
        "evaluation_case_results",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("evaluation_case_results")
    op.drop_table("evaluation_runs")
    op.drop_table("agent_runs")
    op.drop_table("agent_executions")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("agent_configurations")
