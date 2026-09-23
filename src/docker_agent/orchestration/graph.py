from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from docker_agent.orchestration.decision import (
    OrchestrationDecision,
    OrchestrationDecisionModel,
)
from docker_agent.orchestration.delegation import DelegationContext
from docker_agent.orchestration.envelope import SpecialistResultEnvelope
from docker_agent.orchestration.execution import (
    DelegationExecutionService,
    OrchestrationExecutionResult,
)

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


class OrchestrationExecutionGraphState(TypedDict):
    """Shadow state for decision plus one specialist execution."""

    question: str
    context: DelegationContext
    source_agent_type: str | None
    explicit_user_clarification: str | None
    prior_specialist_result: SpecialistResultEnvelope | None
    decision: OrchestrationDecision | None
    execution: OrchestrationExecutionResult | None
    terminal_action: OrchestrationTerminalAction | None
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationExecutionGraphResult:
    """Public result for the Phase 9 Step 2 execution shadow graph."""

    decision: OrchestrationDecision
    execution: OrchestrationExecutionResult | None
    context: DelegationContext
    terminal_action: OrchestrationTerminalAction
    trace: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.terminal_action != self.decision.action:
            raise ValueError(
                "terminal_action must match orchestration decision action"
            )

        if self.terminal_action == "clarify":
            if self.execution is not None:
                raise ValueError(
                    "clarify graph result must not contain specialist execution"
                )
            if self.trace != ("decision", "clarify"):
                raise ValueError(
                    "clarify graph trace must end after clarification"
                )
            return

        if self.execution is None or not self.execution.executed:
            raise ValueError(
                "direct/delegate graph result requires specialist execution"
            )
        if self.execution.decision != self.decision:
            raise ValueError(
                "graph execution decision must match graph decision"
            )
        if self.context != self.execution.context:
            raise ValueError(
                "graph context must match specialist execution context"
            )
        if self.trace != (
            "decision",
            self.terminal_action,
            "specialist",
        ):
            raise ValueError(
                "execution graph trace must contain one specialist step"
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


def build_orchestration_execution_graph(
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
):
    """Compile Step 2 decision -> at-most-one-specialist shadow graph."""

    def decision_node(
        state: OrchestrationExecutionGraphState,
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
        state: OrchestrationExecutionGraphState,
    ) -> OrchestrationTerminalAction:
        decision = state["decision"]
        if decision is None:
            raise ValueError("orchestration graph decision is missing")
        return decision.action

    def clarify_node(
        state: OrchestrationExecutionGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action != "clarify":
            raise ValueError(
                "clarify node requires a clarify decision"
            )
        return {
            "terminal_action": "clarify",
            "trace": (*state["trace"], "clarify"),
        }

    def specialist_node(
        state: OrchestrationExecutionGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None:
            raise ValueError(
                "specialist node requires an orchestration decision"
            )
        if decision.action not in {"direct", "delegate"}:
            raise ValueError(
                "specialist node requires direct or delegate decision"
            )

        execution = execution_service.execute(
            state["question"],
            decision=decision,
            context=state["context"],
            explicit_user_clarification=(
                state["explicit_user_clarification"]
            ),
            prior_specialist_result=(
                state["prior_specialist_result"]
                if decision.action == "delegate"
                else None
            ),
        )
        return {
            "execution": execution,
            "context": execution.context,
            "terminal_action": decision.action,
            "trace": (
                *state["trace"],
                decision.action,
                "specialist",
            ),
        }

    builder = StateGraph(OrchestrationExecutionGraphState)
    builder.add_node("decision", decision_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("specialist", specialist_node)

    builder.add_edge(START, "decision")
    builder.add_conditional_edges(
        "decision",
        decision_edge,
        {
            "clarify": "clarify",
            "direct": "specialist",
            "delegate": "specialist",
        },
    )
    builder.add_edge("clarify", END)
    builder.add_edge("specialist", END)
    return builder.compile()


def run_orchestration_execution_graph(
    question: str,
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
    context: DelegationContext | None = None,
    source_agent_type: str | None = None,
    explicit_user_clarification: str | None = None,
    prior_specialist_result: SpecialistResultEnvelope | None = None,
) -> OrchestrationExecutionGraphResult:
    """Run one Step 2 shadow turn with at most one specialist execution."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    active_context = context or DelegationContext(
        original_query=normalized
    )
    graph = build_orchestration_execution_graph(
        decision_model=decision_model,
        execution_service=execution_service,
    )
    result = graph.invoke(
        OrchestrationExecutionGraphState(
            question=normalized,
            context=active_context,
            source_agent_type=source_agent_type,
            explicit_user_clarification=explicit_user_clarification,
            prior_specialist_result=prior_specialist_result,
            decision=None,
            execution=None,
            terminal_action=None,
            trace=(),
        )
    )

    decision = result.get("decision")
    execution = result.get("execution")
    terminal_action = result.get("terminal_action")
    final_context = result.get("context")
    trace = result.get("trace")

    if not isinstance(decision, OrchestrationDecision):
        raise TypeError(
            "execution graph completed without an orchestration decision"
        )
    if (
        execution is not None
        and not isinstance(execution, OrchestrationExecutionResult)
    ):
        raise TypeError(
            "execution graph returned an invalid specialist execution"
        )
    if terminal_action not in {"clarify", "direct", "delegate"}:
        raise ValueError(
            "execution graph completed without a terminal action"
        )
    if not isinstance(final_context, DelegationContext):
        raise TypeError(
            "execution graph completed without delegation context"
        )
    if not isinstance(trace, tuple):
        raise TypeError(
            "execution graph completed without a trace"
        )

    return OrchestrationExecutionGraphResult(
        decision=decision,
        execution=execution,
        context=final_context,
        terminal_action=terminal_action,
        trace=trace,
    )


__all__ = [
    "OrchestrationDecisionGraphResult",
    "OrchestrationExecutionGraphResult",
    "OrchestrationExecutionGraphState",
    "OrchestrationDecisionGraphState",
    "OrchestrationTerminalAction",
    "build_orchestration_decision_graph",
    "build_orchestration_execution_graph",
    "run_orchestration_decision_graph",
    "run_orchestration_execution_graph",
]
