from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from docker_agent.orchestration.decision import (
    OrchestrationDecision,
    OrchestrationDecisionModel,
)
from docker_agent.orchestration.delegation import DelegationContext

OrchestrationTerminalAction = Literal["clarify", "direct", "delegate"]


class OrchestrationDecisionGraphState(TypedDict):
    """Bounded state for the Phase 9 platform decision graph."""

    question: str
    context: DelegationContext
    source_agent_type: str | None
    decision: OrchestrationDecision | None
    terminal_action: OrchestrationTerminalAction | None
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationDecisionGraphResult:
    """Public result returned by the shadow orchestration decision graph."""

    decision: OrchestrationDecision
    context: DelegationContext
    terminal_action: OrchestrationTerminalAction
    trace: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.terminal_action != self.decision.action:
            raise ValueError(
                "terminal_action must match orchestration decision action"
            )
        if self.trace != ("decision", self.terminal_action):
            raise ValueError(
                "decision graph trace must contain decision and one terminal"
            )


def build_orchestration_decision_graph(
    decision_model: OrchestrationDecisionModel,
):
    """Compile the Phase 9 Step 1 platform-level decision graph."""

    def decision_node(
        state: OrchestrationDecisionGraphState,
    ) -> dict[str, object]:
        decision = decision_model.decide(
            state["question"],
            context=state["context"],
            source_agent_type=state["source_agent_type"],
        )
        return {
            "decision": decision,
            "trace": (*state["trace"], "decision"),
        }

    def decision_edge(
        state: OrchestrationDecisionGraphState,
    ) -> OrchestrationTerminalAction:
        decision = state["decision"]
        if decision is None:
            raise ValueError("orchestration graph decision is missing")
        return decision.action

    def terminal_node(
        action: OrchestrationTerminalAction,
    ):
        def node(
            state: OrchestrationDecisionGraphState,
        ) -> dict[str, object]:
            decision = state["decision"]
            if decision is None:
                raise ValueError(
                    "terminal node requires an orchestration decision"
                )
            if decision.action != action:
                raise ValueError(
                    f"{action} terminal received {decision.action!r}"
                )
            return {
                "terminal_action": action,
                "trace": (*state["trace"], action),
            }

        return node

    builder = StateGraph(OrchestrationDecisionGraphState)
    builder.add_node("decision", decision_node)
    builder.add_node("clarify", terminal_node("clarify"))
    builder.add_node("direct", terminal_node("direct"))
    builder.add_node("delegate", terminal_node("delegate"))

    builder.add_edge(START, "decision")
    builder.add_conditional_edges(
        "decision",
        decision_edge,
        {
            "clarify": "clarify",
            "direct": "direct",
            "delegate": "delegate",
        },
    )
    builder.add_edge("clarify", END)
    builder.add_edge("direct", END)
    builder.add_edge("delegate", END)
    return builder.compile()


def run_orchestration_decision_graph(
    question: str,
    *,
    decision_model: OrchestrationDecisionModel,
    context: DelegationContext | None = None,
    source_agent_type: str | None = None,
) -> OrchestrationDecisionGraphResult:
    """Run one shadow platform-routing turn without executing a specialist."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    active_context = context or DelegationContext(
        original_query=normalized
    )
    graph = build_orchestration_decision_graph(decision_model)
    result = graph.invoke(
        OrchestrationDecisionGraphState(
            question=normalized,
            context=active_context,
            source_agent_type=source_agent_type,
            decision=None,
            terminal_action=None,
            trace=(),
        )
    )

    decision = result.get("decision")
    terminal_action = result.get("terminal_action")
    trace = result.get("trace")
    if not isinstance(decision, OrchestrationDecision):
        raise TypeError(
            "orchestration decision graph completed without a decision"
        )
    if terminal_action not in {"clarify", "direct", "delegate"}:
        raise ValueError(
            "orchestration decision graph completed without a terminal action"
        )
    if not isinstance(trace, tuple):
        raise TypeError(
            "orchestration decision graph completed without a trace"
        )

    return OrchestrationDecisionGraphResult(
        decision=decision,
        context=active_context,
        terminal_action=terminal_action,
        trace=trace,
    )


__all__ = [
    "OrchestrationDecisionGraphResult",
    "OrchestrationDecisionGraphState",
    "OrchestrationTerminalAction",
    "build_orchestration_decision_graph",
    "run_orchestration_decision_graph",
]
