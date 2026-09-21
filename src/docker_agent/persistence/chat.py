from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from sqlalchemy.engine import Engine

from docker_agent.api.chat import ChatSessionManager
from docker_agent.graph.service import LangGraphAgentTurnResult
from docker_agent.persistence.adapter import (
    PersistedAgentTurn,
    persist_langgraph_turn,
)
from docker_agent.persistence.store import (
    ConversationRecord,
    create_conversation,
    get_conversation,
)


class ConversationAgentTypeMismatch(ValueError):
    """Raised when a conversation belongs to another agent type."""


class ChatConversationMismatch(ValueError):
    """Raised when a temporary clarification session is used with another conversation."""


@dataclass(frozen=True, slots=True)
class PersistentChatTurn:
    """One durable product chat turn plus temporary clarification state."""

    conversation: ConversationRecord
    session_id: str
    session_active: bool
    result: LangGraphAgentTurnResult
    persisted: PersistedAgentTurn


@dataclass(slots=True)
class PersistentChatCoordinator:
    """Separate durable conversation identity from temporary clarification sessions."""

    engine: Engine
    sessions: ChatSessionManager
    agent_type: str = "docker_support"
    _session_conversations: dict[str, str] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        session_id: str | None = None,
    ) -> PersistentChatTurn:
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("message must not be empty")

        conversation = self._resolve_conversation(
            message=normalized_message,
            conversation_id=conversation_id,
            session_id=session_id,
        )
        self._validate_session_conversation(
            session_id=session_id,
            conversation_id=conversation.id,
        )

        resolved_session_id, active, result = self.sessions.chat(
            message=normalized_message,
            session_id=session_id,
        )
        if not isinstance(result, LangGraphAgentTurnResult):
            raise TypeError(
                "PersistentChatCoordinator requires LangGraphAgentTurnResult"
            )

        persisted = persist_langgraph_turn(
            self.engine,
            conversation_id=conversation.id,
            user_message=normalized_message,
            result=result,
        )

        with self._lock:
            if active:
                self._session_conversations[resolved_session_id] = conversation.id
            else:
                self._session_conversations.pop(resolved_session_id, None)

        return PersistentChatTurn(
            conversation=get_conversation(self.engine, conversation.id),
            session_id=resolved_session_id,
            session_active=active,
            result=result,
            persisted=persisted,
        )

    def reset(
        self,
        session_id: str,
        *,
        conversation_id: str | None = None,
    ) -> bool:
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")

        if conversation_id is not None:
            normalized_conversation_id = conversation_id.strip()
            if not normalized_conversation_id:
                raise ValueError("conversation_id must not be empty")
            self._validate_session_conversation(
                session_id=normalized_session_id,
                conversation_id=normalized_conversation_id,
            )

        removed = self.sessions.reset(normalized_session_id)
        with self._lock:
            self._session_conversations.pop(normalized_session_id, None)
        return removed

    def reset_conversation_sessions(
        self,
        conversation_id: str,
    ) -> int:
        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id must not be empty")

        with self._lock:
            session_ids = [
                session_id
                for session_id, bound_conversation_id
                in self._session_conversations.items()
                if bound_conversation_id == normalized_conversation_id
            ]

        removed = 0
        for session_id in session_ids:
            if self.sessions.reset(session_id):
                removed += 1
            with self._lock:
                self._session_conversations.pop(session_id, None)

        return removed

    def _resolve_conversation(
        self,
        *,
        message: str,
        conversation_id: str | None,
        session_id: str | None,
    ) -> ConversationRecord:
        if conversation_id is None:
            if session_id is not None:
                raise ValueError(
                    "conversation_id is required when continuing a session"
                )
            return create_conversation(
                self.engine,
                agent_type=self.agent_type,
                title=_default_title(message),
            )

        normalized = conversation_id.strip()
        if not normalized:
            raise ValueError("conversation_id must not be empty")

        conversation = get_conversation(self.engine, normalized)
        if conversation.agent_type != self.agent_type:
            raise ConversationAgentTypeMismatch(
                f"conversation agent_type={conversation.agent_type!r} "
                f"does not match {self.agent_type!r}"
            )
        return conversation

    def _validate_session_conversation(
        self,
        *,
        session_id: str | None,
        conversation_id: str,
    ) -> None:
        if session_id is None:
            return

        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")

        with self._lock:
            bound_conversation_id = self._session_conversations.get(
                normalized_session_id
            )

        if (
            bound_conversation_id is not None
            and bound_conversation_id != conversation_id
        ):
            raise ChatConversationMismatch(
                "session_id belongs to another conversation"
            )


def _default_title(message: str, *, max_chars: int = 60) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"
