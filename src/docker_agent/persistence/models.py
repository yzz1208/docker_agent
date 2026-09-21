from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class PersistenceBase(DeclarativeBase):
    """Metadata root for product-facing persistence tables."""


class AgentConfiguration(PersistenceBase):
    __tablename__ = "agent_configurations"

    agent_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_settings: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
    )
    retrieval_settings: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
    )
    runtime_settings: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class Conversation(PersistenceBase):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class Message(PersistenceBase):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    use_docs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    clarification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )


class AgentExecution(PersistenceBase):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("messages.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    planned_workers: Mapped[list[str]] = mapped_column(JSON)
    completed_workers: Mapped[list[str]] = mapped_column(JSON)
    worker_trace: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
