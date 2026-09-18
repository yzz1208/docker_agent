from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.service import AgentTurnResult, DockerSupportAgent


@dataclass(slots=True)
class ConversationState:
    """Minimal in-memory state for a clarification-aware agent conversation."""

    pending_question: str | None = None


class AgentConversation:
    """Resolve follow-up clarification turns without persisting hidden tool plans."""

    def __init__(
        self,
        agent: DockerSupportAgent,
        *,
        state: ConversationState | None = None,
    ) -> None:
        self.agent = agent
        self.state = state or ConversationState()

    def handle(self, user_message: str) -> AgentTurnResult:
        message = user_message.strip()
        if not message:
            raise ValueError("user_message must not be empty")

        if self.state.pending_question is None:
            effective_question = message
        else:
            effective_question = (
                f"{self.state.pending_question}\n"
                f"User clarification: {message}"
            )

        result = self.agent.handle(effective_question)

        if result.needs_clarification:
            if self.state.pending_question is None:
                self.state.pending_question = effective_question
        else:
            self.state.pending_question = None

        return result

    def reset(self) -> None:
        """Drop pending clarification state."""

        self.state.pending_question = None
