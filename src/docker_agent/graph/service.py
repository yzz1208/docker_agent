from __future__ import annotations

from docker_agent.agent.dynamic_service import (
    DynamicAgentTurnResult,
    DynamicDockerSupportAgent,
)
from docker_agent.graph.state import GraphState
from docker_agent.graph.workflow import run_support_graph


class LangGraphDockerSupportAgent(DynamicDockerSupportAgent):
    """Compatibility service backed by the unified coarse LangGraph workflow."""

    def handle_graph(self, question: str) -> GraphState:
        """Run one graph turn and expose the final GraphState for evaluation."""

        normalized = question.strip()
        if not normalized:
            raise ValueError("question must not be empty")

        return run_support_graph(
            normalized,
            router_model=self.router_model,
            planner_model=self.planner_model,
            answer_model=self.answer_model,
            docker_tools=self.docker_tools,
            docs_retriever=self.docs_retriever,
            max_steps=self.settings.dynamic_runtime_max_steps,
            evidence_max_chars=self.settings.runtime_evidence_max_chars,
        )

    def handle(self, question: str) -> DynamicAgentTurnResult:
        """Keep the existing agent service contract while using LangGraph."""

        state = self.handle_graph(question)
        decision = state["decision"]
        if decision is None:
            raise ValueError("graph completed without a route decision")

        return DynamicAgentTurnResult(
            decision=decision,
            answer=state["answer"],
            runtime_trace=state["runtime_trace"],
        )
