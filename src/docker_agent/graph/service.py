from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.dynamic_service import (
    DynamicAgentTurnResult,
    DynamicDockerSupportAgent,
)
from docker_agent.graph.state import GraphState
from docker_agent.graph.workflow import run_support_graph
from docker_agent.multi_agent.execution import WorkerExecutionRecord
from docker_agent.multi_agent.supervisor import SupervisorPlan


@dataclass(frozen=True, slots=True)
class LangGraphAgentTurnResult(DynamicAgentTurnResult):
    """Agent turn plus the supervisor plan and compact worker execution trace."""

    supervisor_plan: SupervisorPlan
    worker_trace: tuple[WorkerExecutionRecord, ...]


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

    def handle(self, question: str) -> LangGraphAgentTurnResult:
        """Keep legacy fields while exposing multi-agent execution metadata."""

        state = self.handle_graph(question)
        decision = state["decision"]
        supervisor_plan = state["supervisor_plan"]
        if decision is None:
            raise ValueError("graph completed without a route decision")
        if supervisor_plan is None:
            raise ValueError("graph completed without a supervisor plan")

        return LangGraphAgentTurnResult(
            decision=decision,
            answer=state["answer"],
            runtime_trace=state["runtime_trace"],
            supervisor_plan=supervisor_plan,
            worker_trace=state["worker_trace"],
        )
