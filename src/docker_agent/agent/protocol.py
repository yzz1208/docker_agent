from __future__ import annotations

from typing import Protocol

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.router import AgentRouteDecision


class AgentTurnProtocol(Protocol):
    """Minimal turn shape consumed by chat/session infrastructure."""

    decision: AgentRouteDecision
    answer: AgentAnswer | None

    @property
    def needs_clarification(self) -> bool:
        """Whether this turn requires a user follow-up."""


class AgentProtocol(Protocol):
    """Minimal runtime contract shared by platform Agents."""

    def handle(self, question: str) -> AgentTurnProtocol:
        """Handle one user turn."""
