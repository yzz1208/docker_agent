from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.protocol import AgentProtocol, AgentTurnProtocol
from docker_agent.conversation_context import apply_conversation_context


@dataclass(slots=True)
class ConversationState:
    """Minimal in-memory state for a clarification-aware agent conversation."""

    pending_question: str | None = None
    pending_context: str | None = None


class AgentConversation:
    """Resolve clarification turns while preserving the initial turn context."""

    def __init__(
        self,
        agent: AgentProtocol,
        *,
        state: ConversationState | None = None,
    ) -> None:
        self.agent = agent
        self.state = state or ConversationState()

    def handle(
        self,
        user_message: str,
        *,
        context: str | None = None,
    ) -> AgentTurnProtocol:
        message = user_message.strip()
        if not message:
            raise ValueError("user_message must not be empty")

        if self.state.pending_question is None:
            raw_question = message
            resolved_context = _normalize_context(context)
        else:
            raw_question = (
                f"{self.state.pending_question}\n"
                f"User clarification: {message}"
            )
            resolved_context = self.state.pending_context

        effective_question = apply_conversation_context(
            raw_question,
            resolved_context,
        )
        result = self.agent.handle(effective_question)

        if result.needs_clarification:
            self.state.pending_question = raw_question
            self.state.pending_context = resolved_context
        else:
            self.state.pending_question = None
            self.state.pending_context = None

        return result

    def reset(self) -> None:
        """Drop pending clarification and context state."""

        self.state.pending_question = None
        self.state.pending_context = None


def _normalize_context(context: str | None) -> str | None:
    if context is None:
        return None
    normalized = context.strip()
    return normalized or None
