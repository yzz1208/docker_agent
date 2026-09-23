from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from docker_agent.orchestration.checkpoint import (
    orchestration_thread_config,
)
from docker_agent.orchestration.decision import (
    OrchestrationDecision,
    OrchestrationDecisionModel,
)
from docker_agent.orchestration.delegation import DelegationContext
from docker_agent.orchestration.envelope import SpecialistResultEnvelope
from docker_agent.orchestration.execution import (
    DelegationExecutionService,
)
from docker_agent.orchestration.synthesis import (
    OrchestratedSynthesisResult,
    OrchestratedSynthesisService,
)

CheckpointTerminalAction = Literal["clarify", "direct", "delegate"]


class OrchestrationCheckpointGraphState(TypedDict):
    """Persistable public-only state for Phase 9 checkpoint/resume."""

    question: str
    context: DelegationContext
    source_agent_type: str | None
    explicit_user_clarification: str | None
    user_observations: tuple[str, ...]
    prior_specialist_result: SpecialistResultEnvelope | None
    decision: OrchestrationDecision | None
    current_specialist_result: SpecialistResultEnvelope | None
    synthesis: OrchestratedSynthesisResult | None
    final_answer: str | None
    final_clarification: str | None
    terminal_action: CheckpointTerminalAction | None
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationCheckpointRunResult:
    thread_id: str
    completed: bool
    next_nodes: tuple[str, ...]
    decision: OrchestrationDecision | None
    current_specialist_result: SpecialistResultEnvelope | None
    synthesis: OrchestratedSynthesisResult | None
    context: DelegationContext | None
    answer: str | None
    clarification: str | None
    trace: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.thread_id.strip():
            raise ValueError("thread_id must not be empty")
        if self.completed and self.next_nodes:
            raise ValueError(
                "completed checkpoint run must not have pending nodes"
            )
        if not self.completed and not self.next_nodes:
            raise ValueError(
                "paused checkpoint run must expose pending nodes"
            )
        if self.answer is not None and self.clarification is not None:
            raise ValueError(
                "checkpoint run cannot contain answer and clarification"
            )


def build_checkpointed_orchestration_graph(
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
    synthesis_service: OrchestratedSynthesisService,
    checkpointer: BaseCheckpointSaver,
):
    """Compile the public-state-only checkpointed orchestration graph."""

    def decision_node(
        state: OrchestrationCheckpointGraphState,
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
        state: OrchestrationCheckpointGraphState,
    ) -> CheckpointTerminalAction:
        decision = state["decision"]
        if decision is None:
            raise ValueError("checkpoint graph decision is missing")
        return decision.action

    def clarify_node(
        state: OrchestrationCheckpointGraphState,
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
        state: OrchestrationCheckpointGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None:
            raise ValueError(
                "specialist node requires orchestration decision"
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
        result = execution.result_envelope
        if result is None:
            raise ValueError(
                "specialist execution produced no public result"
            )

        return {
            "current_specialist_result": result,
            "context": execution.context,
            "terminal_action": decision.action,
            "trace": (
                *state["trace"],
                decision.action,
                "specialist",
            ),
        }

    def post_specialist_edge(
        state: OrchestrationCheckpointGraphState,
    ) -> Literal["complete", "synthesis"]:
        decision = state["decision"]
        result = state["current_specialist_result"]
        if decision is None or result is None:
            raise ValueError(
                "post-specialist routing requires public result"
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
        state: OrchestrationCheckpointGraphState,
    ) -> dict[str, object]:
        result = state["current_specialist_result"]
        if result is None:
            raise ValueError(
                "completion node requires public specialist result"
            )
        if result.needs_clarification:
            if result.clarification is None:
                raise ValueError(
                    "specialist clarification has no question"
                )
            return {
                "final_clarification": result.clarification,
                "trace": (*state["trace"], "complete"),
            }
        if result.summary is None:
            raise ValueError(
                "completed specialist result has no public summary"
            )
        return {
            "final_answer": result.summary,
            "trace": (*state["trace"], "complete"),
        }

    def synthesis_node(
        state: OrchestrationCheckpointGraphState,
    ) -> dict[str, object]:
        prior = state["prior_specialist_result"]
        current = state["current_specialist_result"]
        if prior is None or current is None:
            raise ValueError(
                "synthesis requires prior and current public results"
            )

        synthesis = synthesis_service.synthesize(
            original_query=state["context"].original_query,
            user_observations=state["user_observations"],
            specialist_results=(prior, current),
        )
        if synthesis.needs_clarification:
            return {
                "synthesis": synthesis,
                "final_clarification": (
                    synthesis.clarification_questions[0]
                ),
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

    builder = StateGraph(OrchestrationCheckpointGraphState)
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
    return builder.compile(checkpointer=checkpointer)


def start_checkpointed_orchestration(
    graph,
    *,
    thread_id: str,
    question: str,
    context: DelegationContext | None = None,
    source_agent_type: str | None = None,
    explicit_user_clarification: str | None = None,
    user_observations: tuple[str, ...] = (),
    prior_specialist_result: SpecialistResultEnvelope | None = None,
    interrupt_before: tuple[str, ...] = (),
) -> OrchestrationCheckpointRunResult:
    normalized = question.strip()
    if not normalized:
        raise ValueError("question must not be empty")

    active_context = context or DelegationContext(
        original_query=normalized
    )
    config = orchestration_thread_config(thread_id)
    existing = graph.get_state(config)
    if existing.values:
        raise ValueError(
            "checkpoint thread already contains orchestration state"
        )

    graph.invoke(
        OrchestrationCheckpointGraphState(
            question=normalized,
            context=active_context,
            source_agent_type=source_agent_type,
            explicit_user_clarification=explicit_user_clarification,
            user_observations=user_observations,
            prior_specialist_result=prior_specialist_result,
            decision=None,
            current_specialist_result=None,
            synthesis=None,
            final_answer=None,
            final_clarification=None,
            terminal_action=None,
            trace=(),
        ),
        config,
        interrupt_before=interrupt_before or None,
        durability="sync",
    )
    return read_checkpointed_orchestration(
        graph,
        thread_id=thread_id,
    )


def resume_checkpointed_orchestration(
    graph,
    *,
    thread_id: str,
) -> OrchestrationCheckpointRunResult:
    config = orchestration_thread_config(thread_id)
    snapshot = graph.get_state(config)
    if not snapshot.next:
        raise ValueError(
            "checkpoint thread has no pending orchestration work"
        )

    graph.invoke(
        None,
        config,
        durability="sync",
    )
    return read_checkpointed_orchestration(
        graph,
        thread_id=thread_id,
    )


def read_checkpointed_orchestration(
    graph,
    *,
    thread_id: str,
) -> OrchestrationCheckpointRunResult:
    config = orchestration_thread_config(thread_id)
    snapshot = graph.get_state(config)
    values = snapshot.values
    if not isinstance(values, dict):
        raise TypeError(
            "checkpoint graph state must be a mapping"
        )

    decision = values.get("decision")
    if decision is not None and not isinstance(
        decision,
        OrchestrationDecision,
    ):
        raise TypeError(
            "checkpoint state contains invalid decision"
        )
    result = values.get("current_specialist_result")
    if result is not None and not isinstance(
        result,
        SpecialistResultEnvelope,
    ):
        raise TypeError(
            "checkpoint state contains invalid specialist result"
        )
    synthesis = values.get("synthesis")
    if synthesis is not None and not isinstance(
        synthesis,
        OrchestratedSynthesisResult,
    ):
        raise TypeError(
            "checkpoint state contains invalid synthesis"
        )
    context = values.get("context")
    if context is not None and not isinstance(
        context,
        DelegationContext,
    ):
        raise TypeError(
            "checkpoint state contains invalid delegation context"
        )

    trace = values.get("trace", ())
    if not isinstance(trace, tuple):
        raise TypeError(
            "checkpoint state trace must be a tuple"
        )
    answer = values.get("final_answer")
    clarification = values.get("final_clarification")
    if answer is not None and not isinstance(answer, str):
        raise TypeError("checkpoint answer must be a string")
    if clarification is not None and not isinstance(
        clarification,
        str,
    ):
        raise TypeError(
            "checkpoint clarification must be a string"
        )

    return OrchestrationCheckpointRunResult(
        thread_id=thread_id,
        completed=not snapshot.next,
        next_nodes=tuple(snapshot.next),
        decision=decision,
        current_specialist_result=result,
        synthesis=synthesis,
        context=context,
        answer=answer,
        clarification=clarification,
        trace=trace,
    )


__all__ = [
    "CheckpointTerminalAction",
    "OrchestrationCheckpointGraphState",
    "OrchestrationCheckpointRunResult",
    "build_checkpointed_orchestration_graph",
    "read_checkpointed_orchestration",
    "resume_checkpointed_orchestration",
    "start_checkpointed_orchestration",
]
