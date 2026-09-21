from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from docker_agent.persistence.models import (
    AgentExecution,
    AgentRun,
    Conversation,
    Message,
    PersistenceBase,
    utc_now,
)

MessageRole = Literal["user", "assistant", "system"]


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: str
    agent_type: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    route: str | None
    use_docs: bool | None
    clarification: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: str
    message_id: str
    planned_workers: tuple[str, ...]
    completed_workers: tuple[str, ...]
    worker_trace: tuple[dict[str, object], ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    conversation: ConversationRecord
    messages: tuple[MessageRecord, ...]
    executions: tuple[ExecutionRecord, ...]


class ConversationNotFound(KeyError):
    """Raised when a persistence operation targets an unknown conversation."""


class MessageNotFound(KeyError):
    """Raised when an execution targets an unknown message."""


def init_persistence_store(engine: Engine) -> None:
    """Create product-facing persistence tables."""

    PersistenceBase.metadata.create_all(engine)


def create_conversation(
    engine: Engine,
    *,
    agent_type: str = "docker_support",
    title: str | None = None,
    conversation_id: str | None = None,
) -> ConversationRecord:
    normalized_agent_type = agent_type.strip()
    if not normalized_agent_type:
        raise ValueError("agent_type must not be empty")

    normalized_title = title.strip() if title is not None else None
    if normalized_title == "":
        normalized_title = None

    row = Conversation(
        id=conversation_id or uuid4().hex,
        agent_type=normalized_agent_type,
        title=normalized_title,
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _conversation_record(row)


def append_message(
    engine: Engine,
    *,
    conversation_id: str,
    role: MessageRole,
    content: str,
    route: str | None = None,
    use_docs: bool | None = None,
    clarification: str | None = None,
    message_id: str | None = None,
) -> MessageRecord:
    normalized_conversation_id = conversation_id.strip()
    normalized_content = content.strip()
    if not normalized_conversation_id:
        raise ValueError("conversation_id must not be empty")
    if not normalized_content:
        raise ValueError("content must not be empty")
    if role not in {"user", "assistant", "system"}:
        raise ValueError(f"unsupported message role: {role}")

    with Session(engine) as session:
        if session.get(Conversation, normalized_conversation_id) is None:
            raise ConversationNotFound(normalized_conversation_id)

        row = Message(
            id=message_id or uuid4().hex,
            conversation_id=normalized_conversation_id,
            role=role,
            content=normalized_content,
            route=route,
            use_docs=use_docs,
            clarification=clarification,
        )
        session.add(row)

        conversation = session.get(Conversation, normalized_conversation_id)
        if conversation is None:
            raise ConversationNotFound(normalized_conversation_id)
        conversation.updated_at = utc_now()

        session.commit()
        session.refresh(row)
        return _message_record(row)


def save_execution(
    engine: Engine,
    *,
    message_id: str,
    planned_workers: list[str] | tuple[str, ...],
    completed_workers: list[str] | tuple[str, ...],
    worker_trace: list[dict[str, object]] | tuple[dict[str, object], ...],
    execution_id: str | None = None,
) -> ExecutionRecord:
    normalized_message_id = message_id.strip()
    if not normalized_message_id:
        raise ValueError("message_id must not be empty")

    with Session(engine) as session:
        if session.get(Message, normalized_message_id) is None:
            raise MessageNotFound(normalized_message_id)

        row = AgentExecution(
            id=execution_id or uuid4().hex,
            message_id=normalized_message_id,
            planned_workers=list(planned_workers),
            completed_workers=list(completed_workers),
            worker_trace=[dict(item) for item in worker_trace],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _execution_record(row)


def get_conversation(
    engine: Engine,
    conversation_id: str,
) -> ConversationRecord:
    normalized = conversation_id.strip()
    if not normalized:
        raise ValueError("conversation_id must not be empty")

    with Session(engine) as session:
        row = session.get(Conversation, normalized)
        if row is None:
            raise ConversationNotFound(normalized)
        return _conversation_record(row)


def rename_conversation(
    engine: Engine,
    conversation_id: str,
    *,
    title: str,
) -> ConversationRecord:
    normalized_id = conversation_id.strip()
    normalized_title = title.strip()
    if not normalized_id:
        raise ValueError("conversation_id must not be empty")
    if not normalized_title:
        raise ValueError("title must not be empty")
    if len(normalized_title) > 240:
        raise ValueError("title must not exceed 240 characters")

    with Session(engine) as session:
        row = session.get(Conversation, normalized_id)
        if row is None:
            raise ConversationNotFound(normalized_id)

        row.title = normalized_title
        row.updated_at = utc_now()
        session.commit()
        session.refresh(row)
        return _conversation_record(row)


def delete_conversation(
    engine: Engine,
    conversation_id: str,
) -> None:
    normalized_id = conversation_id.strip()
    if not normalized_id:
        raise ValueError("conversation_id must not be empty")

    with Session(engine) as session:
        row = session.get(Conversation, normalized_id)
        if row is None:
            raise ConversationNotFound(normalized_id)

        message_ids = session.scalars(
            select(Message.id).where(
                Message.conversation_id == normalized_id
            )
        ).all()
        if message_ids:
            session.execute(
                delete(AgentExecution).where(
                    AgentExecution.message_id.in_(message_ids)
                )
            )
        session.execute(
            delete(AgentRun).where(
                AgentRun.conversation_id == normalized_id
            )
        )
        session.execute(
            delete(Message).where(
                Message.conversation_id == normalized_id
            )
        )
        session.delete(row)
        session.commit()


def list_conversations(
    engine: Engine,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[ConversationRecord, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")

    statement = (
        select(Conversation)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .offset(offset)
        .limit(limit)
    )
    with Session(engine) as session:
        rows = session.scalars(statement).all()
        return tuple(_conversation_record(row) for row in rows)


def load_conversation(
    engine: Engine,
    conversation_id: str,
) -> ConversationSnapshot:
    conversation = get_conversation(engine, conversation_id)

    message_statement = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    )
    with Session(engine) as session:
        message_rows = session.scalars(message_statement).all()
        messages = tuple(_message_record(row) for row in message_rows)

        message_ids = [message.id for message in messages]
        if message_ids:
            execution_statement = (
                select(AgentExecution)
                .where(AgentExecution.message_id.in_(message_ids))
                .order_by(AgentExecution.created_at, AgentExecution.id)
            )
            execution_rows = session.scalars(execution_statement).all()
        else:
            execution_rows = []

        executions = tuple(_execution_record(row) for row in execution_rows)

    return ConversationSnapshot(
        conversation=conversation,
        messages=messages,
        executions=executions,
    )


def _conversation_record(row: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        agent_type=row.agent_type,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message_record(row: Message) -> MessageRecord:
    role = row.role
    if role not in {"user", "assistant", "system"}:
        raise ValueError(f"invalid stored message role: {role}")

    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        role=role,
        content=row.content,
        route=row.route,
        use_docs=row.use_docs,
        clarification=row.clarification,
        created_at=row.created_at,
    )


def _execution_record(row: AgentExecution) -> ExecutionRecord:
    return ExecutionRecord(
        id=row.id,
        message_id=row.message_id,
        planned_workers=tuple(str(item) for item in row.planned_workers),
        completed_workers=tuple(str(item) for item in row.completed_workers),
        worker_trace=tuple(dict(item) for item in row.worker_trace),
        created_at=row.created_at,
    )
