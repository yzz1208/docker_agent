from __future__ import annotations

from typing import TypedDict

from docker_agent.agent.answer import AgentAnswer
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.core.state import AgentState
from docker_agent.rag.context import RagContext


class GraphState(TypedDict):
    """Transport state for LangGraph orchestration.

    AgentState remains the canonical domain state. GraphState only carries
    orchestration-specific objects while the migration is in progress.
    """

    agent_state: AgentState
    decision: AgentRouteDecision | None
    docs_context: RagContext | None
    runtime_context: RuntimeEvidenceContext | None
    answer: AgentAnswer | None
