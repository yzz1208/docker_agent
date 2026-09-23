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
from docker_agent.orchestration.synthesis import (
    OrchestratedSynthesisResult,
    OrchestratedSynthesisService,
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


class OrchestrationSynthesisGraphState(TypedDict):
    """Shadow state for decision, one specialist, and optional synthesis."""

    question: str
    context: DelegationContext
    source_agent_type: str | None
    explicit_user_clarification: str | None
    user_observations: tuple[str, ...]
    prior_specialist_result: SpecialistResultEnvelope | None
    decision: OrchestrationDecision | None
    execution: OrchestrationExecutionResult | None
    synthesis: OrchestratedSynthesisResult | None
    final_answer: str | None
    final_clarification: str | None
    terminal_action: OrchestrationTerminalAction | None
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationSynthesisGraphResult:
    """Public result for the Phase 9 Step 3 synthesis shadow graph."""

    decision: OrchestrationDecision
    execution: OrchestrationExecutionResult | None
    synthesis: OrchestratedSynthesisResult | None
    context: DelegationContext
    terminal_action: OrchestrationTerminalAction
    answer: str | None
    clarification: str | None
    trace: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.terminal_action != self.decision.action:
            raise ValueError(
                "terminal_action must match orchestration decision action"
            )
        if self.answer is not None and self.clarification is not None:
            raise ValueError(
                "graph result cannot contain answer and clarification together"
            )

        if self.terminal_action == "clarify":
            if self.execution is not None or self.synthesis is not None:
                raise ValueError(
                    "decision clarification must not execute or synthesize"
                )
            if not self.clarification:
                raise ValueError(
                    "decision clarification requires clarification text"
                )
            if self.trace != ("decision", "clarify"):
                raise ValueError(
                    "decision clarification trace is invalid"
                )
            return

        if self.execution is None or not self.execution.executed:
            raise ValueError(
                "completed graph result requires specialist execution"
            )
        if self.execution.decision != self.decision:
            raise ValueError(
                "graph execution decision must match graph decision"
            )
        if self.context != self.execution.context:
            raise ValueError(
                "graph context must match specialist execution context"
            )

        if self.synthesis is None:
            if self.trace != (
                "decision",
                self.terminal_action,
                "specialist",
                "complete",
            ):
                raise ValueError(
                    "non-synthesis graph trace is invalid"
                )
        else:
            if self.trace != (
                "decision",
                self.terminal_action,
                "specialist",
                "synthesis",
            ):
                raise ValueError(
                    "synthesis graph trace is invalid"
                )

        if self.answer is None and self.clarification is None:
            raise ValueError(
                "completed graph result requires public content"
            )

    @property
    def synthesized(self) -> bool:
        return self.synthesis is not None


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


def build_orchestration_synthesis_graph(
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
    synthesis_service: OrchestratedSynthesisService,
):
    """Compile Step 3 shadow graph with optional provenance-safe synthesis."""

    def decision_node(
        state: OrchestrationSynthesisGraphState,
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
        state: OrchestrationSynthesisGraphState,
    ) -> OrchestrationTerminalAction:
        decision = state["decision"]
        if decision is None:
            raise ValueError("orchestration graph decision is missing")
        return decision.action

    def clarify_node(
        state: OrchestrationSynthesisGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action != "clarify":
            raise ValueError(
                "clarify node requires a clarify decision"
            )
        clarification = decision.clarification
        if clarification is None:
            raise ValueError(
                "clarify decision requires clarification text"
            )
        return {
            "final_clarification": clarification,
            "terminal_action": "clarify",
            "trace": (*state["trace"], "clarify"),
        }

    def specialist_node(
        state: OrchestrationSynthesisGraphState,
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

    def post_specialist_edge(
        state: OrchestrationSynthesisGraphState,
    ) -> Literal["complete", "synthesis"]:
        execution = state["execution"]
        decision = state["decision"]
        if execution is None or decision is None:
            raise ValueError(
                "post-specialist routing requires execution and decision"
            )
        result = execution.result_envelope
        if result is None:
            raise ValueError(
                "specialist execution produced no public result"
            )
        if result.needs_clarification:
            return "complete"
        if (
            decision.action == "delegate"
            and state["prior_specialist_result"] is not None
        ):
            return "synthesis"
        return "complete"

    def complete_node(
        state: OrchestrationSynthesisGraphState,
    ) -> dict[str, object]:
        execution = state["execution"]
        if execution is None or execution.result_envelope is None:
            raise ValueError(
                "completion node requires public specialist result"
            )

        result = execution.result_envelope
        if result.needs_clarification:
            clarification = result.clarification
            if clarification is None:
                raise ValueError(
                    "specialist clarification has no question"
                )
            return {
                "final_clarification": clarification,
                "trace": (*state["trace"], "complete"),
            }

        return {
            "final_answer": _execution_public_answer(execution),
            "trace": (*state["trace"], "complete"),
        }

    def synthesis_node(
        state: OrchestrationSynthesisGraphState,
    ) -> dict[str, object]:
        execution = state["execution"]
        prior = state["prior_specialist_result"]
        if execution is None or execution.result_envelope is None:
            raise ValueError(
                "synthesis node requires current public specialist result"
            )
        if prior is None:
            raise ValueError(
                "synthesis node requires prior public specialist result"
            )

        synthesis = synthesis_service.synthesize(
            original_query=state["context"].original_query,
            user_observations=state["user_observations"],
            specialist_results=(
                prior,
                execution.result_envelope,
            ),
        )
        if synthesis.needs_clarification:
            clarification = synthesis.clarification_questions[0]
            return {
                "synthesis": synthesis,
                "final_clarification": clarification,
                "trace": (*state["trace"], "synthesis"),
            }

        if synthesis.answer is None:
            raise ValueError(
                "completed synthesis has no public answer"
            )
        return {
            "synthesis": synthesis,
            "final_answer": synthesis.answer,
            "trace": (*state["trace"], "synthesis"),
        }

    builder = StateGraph(OrchestrationSynthesisGraphState)
    builder.add_node("decision", decision_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("specialist", specialist_node)
    builder.add_node("complete", complete_node)
    builder.add_node("synthesis", synthesis_node)

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
    builder.add_conditional_edges(
        "specialist",
        post_specialist_edge,
        {
            "complete": "complete",
            "synthesis": "synthesis",
        },
    )
    builder.add_edge("complete", END)
    builder.add_edge("synthesis", END)
    return builder.compile()


def run_orchestration_synthesis_graph(
    question: str,
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
    synthesis_service: OrchestratedSynthesisService,
    context: DelegationContext | None = None,
    source_agent_type: str | None = None,
    explicit_user_clarification: str | None = None,
    user_observations: tuple[str, ...] = (),
    prior_specialist_result: SpecialistResultEnvelope | None = None,
) -> OrchestrationSynthesisGraphResult:
    """Run Step 3 shadow flow through optional cross-Agent synthesis."""

    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    active_context = context or DelegationContext(
        original_query=normalized
    )
    graph = build_orchestration_synthesis_graph(
        decision_model=decision_model,
        execution_service=execution_service,
        synthesis_service=synthesis_service,
    )
    result = graph.invoke(
        OrchestrationSynthesisGraphState(
            question=normalized,
            context=active_context,
            source_agent_type=source_agent_type,
            explicit_user_clarification=explicit_user_clarification,
            user_observations=user_observations,
            prior_specialist_result=prior_specialist_result,
            decision=None,
            execution=None,
            synthesis=None,
            final_answer=None,
            final_clarification=None,
            terminal_action=None,
            trace=(),
        )
    )

    decision = result.get("decision")
    execution = result.get("execution")
    synthesis = result.get("synthesis")
    final_context = result.get("context")
    terminal_action = result.get("terminal_action")
    answer = result.get("final_answer")
    clarification = result.get("final_clarification")
    trace = result.get("trace")

    if not isinstance(decision, OrchestrationDecision):
        raise TypeError(
            "synthesis graph completed without orchestration decision"
        )
    if (
        execution is not None
        and not isinstance(execution, OrchestrationExecutionResult)
    ):
        raise TypeError(
            "synthesis graph returned invalid specialist execution"
        )
    if (
        synthesis is not None
        and not isinstance(synthesis, OrchestratedSynthesisResult)
    ):
        raise TypeError(
            "synthesis graph returned invalid synthesis result"
        )
    if not isinstance(final_context, DelegationContext):
        raise TypeError(
            "synthesis graph completed without delegation context"
        )
    if terminal_action not in {"clarify", "direct", "delegate"}:
        raise ValueError(
            "synthesis graph completed without terminal action"
        )
    if answer is not None and not isinstance(answer, str):
        raise TypeError("synthesis graph answer must be a string")
    if clarification is not None and not isinstance(clarification, str):
        raise TypeError("synthesis graph clarification must be a string")
    if not isinstance(trace, tuple):
        raise TypeError(
            "synthesis graph completed without a trace"
        )

    return OrchestrationSynthesisGraphResult(
        decision=decision,
        execution=execution,
        synthesis=synthesis,
        context=final_context,
        terminal_action=terminal_action,
        answer=answer,
        clarification=clarification,
        trace=trace,
    )


def _execution_public_answer(
    execution: OrchestrationExecutionResult,
) -> str:
    turn = execution.turn
    if turn is not None and turn.answer is not None:
        answer = turn.answer.answer.strip()
        if answer:
            return answer

    result = execution.result_envelope
    if result is not None and result.summary:
        return result.summary

    raise ValueError(
        "completed specialist execution has no public answer"
    )


__all__ = [
    "OrchestrationDecisionGraphResult",
    "OrchestrationDecisionGraphState",
    "OrchestrationExecutionGraphResult",
    "OrchestrationExecutionGraphState",
    "OrchestrationSynthesisGraphResult",
    "OrchestrationSynthesisGraphState",
    "OrchestrationTerminalAction",
    "build_orchestration_decision_graph",
    "build_orchestration_execution_graph",
    "build_orchestration_synthesis_graph",
    "run_orchestration_decision_graph",
    "run_orchestration_execution_graph",
    "run_orchestration_synthesis_graph",
]
