from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from docker_agent.orchestration.approval import (
    ApprovalStatus,
    HumanApprovalPolicy,
    HumanApprovalRequest,
    HumanApprovalResponse,
    approval_request_payload,
    normalize_approval_comment,
    parse_approval_request,
)
from docker_agent.orchestration.checkpoint import (
    orchestration_thread_config,
)
from docker_agent.orchestration.decision import (
    OrchestrationDecision,
    OrchestrationDecisionModel,
)
from docker_agent.orchestration.delegation import DelegationContext
from docker_agent.orchestration.envelope import SpecialistResultEnvelope
from docker_agent.orchestration.execution import DelegationExecutionService
from docker_agent.orchestration.synthesis import (
    OrchestratedSynthesisResult,
    OrchestratedSynthesisService,
)

ApprovalTerminalAction = Literal["clarify", "direct", "delegate"]


class OrchestrationApprovalGraphState(TypedDict):
    """Public-only checkpoint state for Human-in-the-loop orchestration."""

    question: str
    approval_question: str | None
    context: DelegationContext
    source_agent_type: str | None
    explicit_user_clarification: str | None
    user_observations: tuple[str, ...]
    prior_specialist_result: SpecialistResultEnvelope | None
    decision: OrchestrationDecision | None
    approval_status: ApprovalStatus | None
    approval_comment: str | None
    current_specialist_result: SpecialistResultEnvelope | None
    synthesis: OrchestratedSynthesisResult | None
    final_answer: str | None
    final_clarification: str | None
    terminal_action: ApprovalTerminalAction | None
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationApprovalRunResult:
    thread_id: str
    completed: bool
    next_nodes: tuple[str, ...]
    approval_status: ApprovalStatus | None
    approval_request: HumanApprovalRequest | None
    approval_comment: str | None
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
                "completed approval run must not have pending nodes"
            )
        if not self.completed and not self.next_nodes:
            raise ValueError(
                "paused approval run must expose pending nodes"
            )
        if self.answer is not None and self.clarification is not None:
            raise ValueError(
                "approval run cannot contain answer and clarification"
            )
        if self.approval_status == "pending":
            if self.completed:
                raise ValueError(
                    "pending approval run must not be completed"
                )
            if self.approval_request is None:
                raise ValueError(
                    "pending approval run requires interrupt request"
                )
        elif self.approval_request is not None:
            raise ValueError(
                "approval request is only valid while approval is pending"
            )


def build_human_approval_orchestration_graph(
    *,
    decision_model: OrchestrationDecisionModel,
    execution_service: DelegationExecutionService,
    synthesis_service: OrchestratedSynthesisService,
    checkpointer: BaseCheckpointSaver,
    approval_policy: HumanApprovalPolicy | None = None,
):
    """Compile Step 5 graph with a durable Human-in-the-loop approval gate."""

    policy = approval_policy or HumanApprovalPolicy()

    def decision_node(
        state: OrchestrationApprovalGraphState,
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
        state: OrchestrationApprovalGraphState,
    ) -> ApprovalTerminalAction:
        decision = state["decision"]
        if decision is None:
            raise ValueError("approval graph decision is missing")
        return decision.action

    def clarify_node(
        state: OrchestrationApprovalGraphState,
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

    def approval_gate_node(
        state: OrchestrationApprovalGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action == "clarify":
            raise ValueError(
                "approval gate requires direct or delegate decision"
            )
        if policy.requires_approval(decision):
            return {
                "approval_status": "pending",
                "trace": (*state["trace"], "approval_required"),
            }
        return {
            "approval_status": "not_required",
            "trace": (*state["trace"], "approval_skipped"),
        }

    def approval_gate_edge(
        state: OrchestrationApprovalGraphState,
    ) -> Literal["approval", "specialist"]:
        status = state["approval_status"]
        if status == "pending":
            return "approval"
        if status == "not_required":
            return "specialist"
        raise ValueError(
            "approval gate produced invalid approval status"
        )

    def approval_node(
        state: OrchestrationApprovalGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action == "clarify":
            raise ValueError(
                "approval node requires direct or delegate decision"
            )

        response = interrupt(
            approval_request_payload(
                question=(
                    state["approval_question"]
                    or state["question"]
                ),
                decision=decision,
            )
        )
        if not isinstance(response, dict):
            raise TypeError(
                "approval resume payload must be an object"
            )
        approved = response.get("approved")
        if not isinstance(approved, bool):
            raise TypeError(
                "approval resume payload requires boolean approved"
            )
        comment = normalize_approval_comment(
            response.get("comment")
        )
        status: ApprovalStatus = (
            "approved" if approved else "denied"
        )
        return {
            "approval_status": status,
            "approval_comment": comment,
            "trace": (*state["trace"], status),
        }

    def approval_edge(
        state: OrchestrationApprovalGraphState,
    ) -> Literal["specialist", "denied"]:
        status = state["approval_status"]
        if status == "approved":
            return "specialist"
        if status == "denied":
            return "denied"
        raise ValueError(
            "approval node must resolve to approved or denied"
        )

    def denied_node(
        state: OrchestrationApprovalGraphState,
    ) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action == "clarify":
            raise ValueError(
                "denied node requires direct or delegate decision"
            )
        return {
            "final_answer": "操作未获批准，工作流已停止执行。",
            "terminal_action": decision.action,
            "trace": (*state["trace"], "approval_denied"),
        }

    def specialist_node(
        state: OrchestrationApprovalGraphState,
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
        if state["approval_status"] == "pending":
            raise ValueError(
                "specialist cannot execute while approval is pending"
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
        state: OrchestrationApprovalGraphState,
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
        state: OrchestrationApprovalGraphState,
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
        state: OrchestrationApprovalGraphState,
    ) -> dict[str, object]:
        prior = state["prior_specialist_result"]
        current = state["current_specialist_result"]
        if prior is None or current is None:
            raise ValueError(
                "synthesis requires prior and current public results"
            )

        synthesis = synthesis_service.synthesize(
            original_query=state["context"].original_query,
            user_observations=tuple(state["user_observations"]),
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

    builder = StateGraph(OrchestrationApprovalGraphState)
    builder.add_node("decision", decision_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("approval", approval_node)
    builder.add_node("denied", denied_node)
    builder.add_node("specialist", specialist_node)
    builder.add_node("complete", complete_node)
    builder.add_node("synthesis", synthesis_node)

    builder.add_edge(START, "decision")
    builder.add_conditional_edges(
        "decision",
        decision_edge,
        {
            "clarify": "clarify",
            "direct": "approval_gate",
            "delegate": "approval_gate",
        },
    )
    builder.add_edge("clarify", END)
    builder.add_conditional_edges(
        "approval_gate",
        approval_gate_edge,
        {
            "approval": "approval",
            "specialist": "specialist",
        },
    )
    builder.add_conditional_edges(
        "approval",
        approval_edge,
        {
            "specialist": "specialist",
            "denied": "denied",
        },
    )
    builder.add_edge("denied", END)
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


def start_human_approval_orchestration(
    graph,
    *,
    thread_id: str,
    question: str,
    approval_question: str | None = None,
    context: DelegationContext | None = None,
    source_agent_type: str | None = None,
    explicit_user_clarification: str | None = None,
    user_observations: tuple[str, ...] = (),
    prior_specialist_result: SpecialistResultEnvelope | None = None,
) -> OrchestrationApprovalRunResult:
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
            "approval thread already contains orchestration state"
        )

    graph.invoke(
        OrchestrationApprovalGraphState(
            question=normalized,
            approval_question=(
                approval_question.strip()
                if approval_question is not None
                and approval_question.strip()
                else None
            ),
            context=active_context,
            source_agent_type=source_agent_type,
            explicit_user_clarification=explicit_user_clarification,
            user_observations=user_observations,
            prior_specialist_result=prior_specialist_result,
            decision=None,
            approval_status=None,
            approval_comment=None,
            current_specialist_result=None,
            synthesis=None,
            final_answer=None,
            final_clarification=None,
            terminal_action=None,
            trace=(),
        ),
        config,
        durability="sync",
    )
    return read_human_approval_orchestration(
        graph,
        thread_id=thread_id,
    )


def resume_human_approval_orchestration(
    graph,
    *,
    thread_id: str,
    approved: bool,
    comment: str | None = None,
) -> OrchestrationApprovalRunResult:
    config = orchestration_thread_config(thread_id)
    snapshot = graph.get_state(config)
    if len(snapshot.interrupts) != 1:
        raise ValueError(
            "approval thread must have exactly one pending interrupt"
        )

    response: HumanApprovalResponse = {
        "approved": approved,
    }
    normalized_comment = normalize_approval_comment(comment)
    if normalized_comment is not None:
        response["comment"] = normalized_comment

    graph.invoke(
        Command(resume=response),
        config,
        durability="sync",
    )
    return read_human_approval_orchestration(
        graph,
        thread_id=thread_id,
    )


def read_human_approval_orchestration(
    graph,
    *,
    thread_id: str,
) -> OrchestrationApprovalRunResult:
    config = orchestration_thread_config(thread_id)
    snapshot = graph.get_state(config)
    values = snapshot.values
    if not isinstance(values, dict):
        raise TypeError(
            "approval graph state must be a mapping"
        )

    decision = values.get("decision")
    if decision is not None and not isinstance(
        decision,
        OrchestrationDecision,
    ):
        raise TypeError(
            "approval state contains invalid decision"
        )
    result = values.get("current_specialist_result")
    if result is not None and not isinstance(
        result,
        SpecialistResultEnvelope,
    ):
        raise TypeError(
            "approval state contains invalid specialist result"
        )
    synthesis = values.get("synthesis")
    if synthesis is not None and not isinstance(
        synthesis,
        OrchestratedSynthesisResult,
    ):
        raise TypeError(
            "approval state contains invalid synthesis"
        )
    context = values.get("context")
    if context is not None and not isinstance(
        context,
        DelegationContext,
    ):
        raise TypeError(
            "approval state contains invalid delegation context"
        )

    status = values.get("approval_status")
    if status not in {
        None,
        "not_required",
        "pending",
        "approved",
        "denied",
    }:
        raise ValueError(
            "approval state contains invalid approval status"
        )
    comment = values.get("approval_comment")
    if comment is not None and not isinstance(comment, str):
        raise TypeError(
            "approval state comment must be a string"
        )

    trace_raw = values.get("trace", ())
    if not isinstance(trace_raw, (list, tuple)):
        raise TypeError(
            "approval state trace must be a sequence"
        )
    if any(not isinstance(item, str) for item in trace_raw):
        raise TypeError(
            "approval state trace items must be strings"
        )
    trace = tuple(trace_raw)

    answer = values.get("final_answer")
    clarification = values.get("final_clarification")
    if answer is not None and not isinstance(answer, str):
        raise TypeError("approval answer must be a string")
    if clarification is not None and not isinstance(
        clarification,
        str,
    ):
        raise TypeError(
            "approval clarification must be a string"
        )

    approval_request = None
    if snapshot.interrupts:
        if len(snapshot.interrupts) != 1:
            raise ValueError(
                "approval graph supports exactly one pending interrupt"
            )
        pending = snapshot.interrupts[0]
        approval_request = parse_approval_request(
            interrupt_id=pending.id,
            value=pending.value,
        )

    return OrchestrationApprovalRunResult(
        thread_id=thread_id,
        completed=not snapshot.next,
        next_nodes=tuple(snapshot.next),
        approval_status=status,
        approval_request=approval_request,
        approval_comment=comment,
        decision=decision,
        current_specialist_result=result,
        synthesis=synthesis,
        context=context,
        answer=answer,
        clarification=clarification,
        trace=trace,
    )


__all__ = [
    "ApprovalTerminalAction",
    "OrchestrationApprovalGraphState",
    "OrchestrationApprovalRunResult",
    "build_human_approval_orchestration_graph",
    "read_human_approval_orchestration",
    "resume_human_approval_orchestration",
    "start_human_approval_orchestration",
]
