from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from docker_agent.persistence.store import (
    ConversationRecord,
    ConversationSnapshot,
    ExecutionRecord,
    MessageRecord,
)


class ConversationSummaryResponse(BaseModel):
    id: str
    agent_type: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationExecutionResponse(BaseModel):
    id: str
    planned_workers: list[str] = Field(default_factory=list)
    completed_workers: list[str] = Field(default_factory=list)
    worker_trace: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime


class ConversationMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    route: str | None
    use_docs: bool | None
    clarification: str | None
    created_at: datetime
    execution: ConversationExecutionResponse | None = None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummaryResponse
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


def build_conversation_summary(
    record: ConversationRecord,
) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=record.id,
        agent_type=record.agent_type,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_conversation_detail(
    snapshot: ConversationSnapshot,
) -> ConversationDetailResponse:
    execution_by_message = {
        execution.message_id: execution
        for execution in snapshot.executions
    }
    return ConversationDetailResponse(
        conversation=build_conversation_summary(snapshot.conversation),
        messages=[
            _build_message_response(
                message,
                execution_by_message.get(message.id),
            )
            for message in snapshot.messages
        ],
    )


def _build_message_response(
    message: MessageRecord,
    execution: ExecutionRecord | None,
) -> ConversationMessageResponse:
    execution_response = None
    if execution is not None:
        execution_response = ConversationExecutionResponse(
            id=execution.id,
            planned_workers=list(execution.planned_workers),
            completed_workers=list(execution.completed_workers),
            worker_trace=[dict(item) for item in execution.worker_trace],
            created_at=execution.created_at,
        )

    return ConversationMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        route=message.route,
        use_docs=message.use_docs,
        clarification=message.clarification,
        created_at=message.created_at,
        execution=execution_response,
    )
