from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, Field

from docker_agent.agent.conversation import AgentConversation
from docker_agent.agent.protocol import (
    AgentProtocol,
    AgentTurnProtocol,
    PersistableAgentTurnProtocol,
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    agent_type: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None


class RuntimeSourceResponse(BaseModel):
    index: int
    tool: str
    command: list[str]
    ok: bool


class DocSourceResponse(BaseModel):
    index: int
    title: str
    section: str
    source_url: str


class WorkerExecutionResponse(BaseModel):
    index: int
    role: str
    tool_results_added: int
    evidence_added: int
    runtime_steps_added: int
    answer_created: bool


class AgentExecutionResponse(BaseModel):
    planned_workers: list[str] = Field(default_factory=list)
    completed_workers: list[str] = Field(default_factory=list)
    worker_trace: list[WorkerExecutionResponse] = Field(default_factory=list)


class ChatResponse(BaseModel):
    agent_type: str
    conversation_id: str | None = None
    session_id: str
    session_active: bool
    route: str
    reason: str
    use_docs: bool
    clarification: str | None = None
    answer: str | None = None
    runtime_sources: list[RuntimeSourceResponse] = Field(default_factory=list)
    doc_sources: list[DocSourceResponse] = Field(default_factory=list)
    execution: AgentExecutionResponse | None = None


class ChatSessionNotFound(KeyError):
    """Raised when a follow-up references an unknown or completed session."""


@dataclass(slots=True)
class ChatSessionManager:
    """Keep only active clarification sessions in memory."""

    agent_factory: Callable[[], AgentProtocol]
    agent_type: str = "docker_support"
    _sessions: dict[str, AgentConversation] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def chat(
        self,
        *,
        message: str,
        session_id: str | None = None,
        context: str | None = None,
    ) -> tuple[str, bool, AgentTurnProtocol]:
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")

        with self._lock:
            if session_id is None:
                resolved_session_id = uuid4().hex
                conversation = AgentConversation(self.agent_factory())
            else:
                resolved_session_id = session_id.strip()
                if not resolved_session_id:
                    raise ValueError("session_id must not be empty")
                try:
                    conversation = self._sessions[resolved_session_id]
                except KeyError as exc:
                    raise ChatSessionNotFound(resolved_session_id) from exc

        result = conversation.handle(
            message,
            context=context,
        )

        with self._lock:
            if result.needs_clarification:
                self._sessions[resolved_session_id] = conversation
                active = True
            else:
                self._sessions.pop(resolved_session_id, None)
                active = False

        return resolved_session_id, active, result

    def reset(self, session_id: str) -> bool:
        session_id = session_id.strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def active_sessions(self) -> int:
        with self._lock:
            return len(self._sessions)


def build_chat_response(
    session_id: str,
    session_active: bool,
    result: AgentTurnProtocol,
    *,
    agent_type: str = "docker_support",
    conversation_id: str | None = None,
) -> ChatResponse:
    """Serialize an agent turn without exposing raw runtime output."""

    decision = result.decision
    runtime_sources: list[RuntimeSourceResponse] = []
    doc_sources: list[DocSourceResponse] = []
    answer_text: str | None = None
    execution: AgentExecutionResponse | None = None

    if isinstance(result, PersistableAgentTurnProtocol):
        execution = AgentExecutionResponse(
            planned_workers=list(result.supervisor_plan.workers),
            completed_workers=[record.role for record in result.worker_trace],
            worker_trace=[
                WorkerExecutionResponse(
                    index=record.index,
                    role=record.role,
                    tool_results_added=record.tool_results_added,
                    evidence_added=record.evidence_added,
                    runtime_steps_added=record.runtime_steps_added,
                    answer_created=record.answer_created,
                )
                for record in result.worker_trace
            ],
        )

    if result.answer is not None:
        answer_text = result.answer.answer
        runtime_sources = [
            RuntimeSourceResponse(
                index=source.index,
                tool=source.tool,
                command=list(source.command),
                ok=source.ok,
            )
            for source in result.answer.cited_runtime_sources
        ]
        doc_sources = [
            DocSourceResponse(
                index=source.index,
                title=source.title,
                section=source.section,
                source_url=source.source_url,
            )
            for source in result.answer.cited_doc_sources
        ]

    return ChatResponse(
        agent_type=agent_type,
        conversation_id=conversation_id,
        session_id=session_id,
        session_active=session_active,
        route=decision.route,
        reason=decision.reason,
        use_docs=decision.use_docs,
        clarification=decision.clarification if result.needs_clarification else None,
        answer=answer_text,
        runtime_sources=runtime_sources,
        doc_sources=doc_sources,
        execution=execution,
    )
