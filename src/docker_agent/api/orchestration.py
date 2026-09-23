from __future__ import annotations

from pydantic import BaseModel, Field

from docker_agent.orchestration.auto_chat import (
    AutoOrchestrationTurn,
    AutoTraceStep,
)


class AutoChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class AutoApprovalDecisionRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=1_000)


class AutoApprovalRequestResponse(BaseModel):
    interrupt_id: str
    action: str
    source_agent_type: str | None = None
    target_agent_type: str
    capability: str
    reason: str
    question: str
    response_schema: dict[str, object]


class AutoTraceStepResponse(BaseModel):
    stage: str
    label: str
    agent_type: str | None = None
    capability: str | None = None
    reason: str


class AutoSpecialistResultResponse(BaseModel):
    agent_type: str
    route: str
    reason: str
    needs_clarification: bool
    clarification: str | None = None
    summary: str | None = None


class AutoChatResponse(BaseModel):
    mode: str = "auto"
    conversation_id: str
    current_agent_type: str | None = None
    route: str
    answer: str | None = None
    clarification: str | None = None
    needs_clarification: bool
    synthesized: bool
    trace: list[AutoTraceStepResponse] = Field(default_factory=list)
    specialist_results: list[AutoSpecialistResultResponse] = Field(
        default_factory=list
    )
    approval_status: str | None = None
    needs_approval: bool = False
    approval_request: AutoApprovalRequestResponse | None = None


def build_auto_chat_response(
    turn: AutoOrchestrationTurn,
) -> AutoChatResponse:
    return AutoChatResponse(
        conversation_id=turn.conversation.id,
        current_agent_type=turn.current_agent_type,
        route=turn.route,
        answer=turn.answer,
        clarification=turn.clarification,
        needs_clarification=turn.needs_clarification,
        synthesized=turn.synthesized,
        trace=[_build_trace_step(item) for item in turn.trace],
        specialist_results=[
            AutoSpecialistResultResponse(
                agent_type=item.agent_type,
                route=item.route,
                reason=item.reason,
                needs_clarification=item.needs_clarification,
                clarification=item.clarification,
                summary=item.summary,
            )
            for item in turn.specialist_results
        ],
        approval_status=turn.approval_status,
        needs_approval=turn.needs_approval,
        approval_request=(
            AutoApprovalRequestResponse(
                interrupt_id=turn.approval_request.interrupt_id,
                action=turn.approval_request.action,
                source_agent_type=(
                    turn.approval_request.source_agent_type
                ),
                target_agent_type=(
                    turn.approval_request.target_agent_type
                ),
                capability=turn.approval_request.capability,
                reason=turn.approval_request.reason,
                question=turn.approval_request.question,
                response_schema=(
                    turn.approval_request.response_schema
                ),
            )
            if turn.approval_request is not None
            else None
        ),
    )


def _build_trace_step(step: AutoTraceStep) -> AutoTraceStepResponse:
    return AutoTraceStepResponse(
        stage=step.stage,
        label=step.label,
        agent_type=step.agent_type,
        capability=step.capability,
        reason=step.reason,
    )


__all__ = [
    "AutoApprovalDecisionRequest",
    "AutoApprovalRequestResponse",
    "AutoChatRequest",
    "AutoChatResponse",
    "AutoSpecialistResultResponse",
    "AutoTraceStepResponse",
    "build_auto_chat_response",
]
