from __future__ import annotations

from typing import Protocol, runtime_checkable

from docker_agent.agent.answer import AgentAnswer


class AgentDecisionProtocol(Protocol):
    """Decision metadata exposed by any platform Agent turn."""

    route: str
    reason: str
    clarification: str | None
    use_docs: bool


class AgentExecutionPlanProtocol(Protocol):
    """Worker plan metadata persisted for one Agent turn."""

    workers: tuple[str, ...]


class AgentWorkerExecutionProtocol(Protocol):
    """Compact worker execution metadata persisted for one Agent turn."""

    index: int
    role: str
    tool_results_added: int
    evidence_added: int
    runtime_steps_added: int
    answer_created: bool


class AgentTurnProtocol(Protocol):
    """Minimal turn shape consumed by chat/session infrastructure."""

    decision: AgentDecisionProtocol
    answer: AgentAnswer | None

    @property
    def needs_clarification(self) -> bool:
        """Whether this turn requires a user follow-up."""
        ...


@runtime_checkable
class PersistableAgentTurnProtocol(AgentTurnProtocol, Protocol):
    """Turn contract required by durable chat persistence and telemetry."""

    supervisor_plan: AgentExecutionPlanProtocol
    worker_trace: tuple[AgentWorkerExecutionProtocol, ...]


class AgentProtocol(Protocol):
    """Minimal runtime contract shared by platform Agents."""

    def handle(self, question: str) -> AgentTurnProtocol:
        """Handle one user turn."""
        ...
