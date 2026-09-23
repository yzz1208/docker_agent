from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from docker_agent.orchestration.decision import OrchestrationDecision

ApprovalAction = Literal["direct", "delegate"]
ApprovalStatus = Literal[
    "not_required",
    "pending",
    "approved",
    "denied",
]


class HumanApprovalResponse(TypedDict):
    approved: bool
    comment: NotRequired[str]


@dataclass(frozen=True, slots=True)
class HumanApprovalPolicy:
    """Policy deciding which validated orchestration decisions require approval."""

    required_actions: frozenset[ApprovalAction] = frozenset({"delegate"})
    required_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        unsupported = set(self.required_actions) - {"direct", "delegate"}
        if unsupported:
            raise ValueError(
                "approval required_actions may contain only direct/delegate"
            )
        for capability in self.required_capabilities:
            if not capability.strip():
                raise ValueError(
                    "approval required_capabilities must not contain empty values"
                )

    def requires_approval(
        self,
        decision: OrchestrationDecision,
    ) -> bool:
        if decision.action == "clarify":
            return False
        if decision.action in self.required_actions:
            return True
        capability = decision.capability
        return (
            capability is not None
            and capability in self.required_capabilities
        )


def approval_request_payload(
    *,
    question: str,
    decision: OrchestrationDecision,
) -> dict[str, object]:
    """Build the bounded public request surfaced through LangGraph interrupt."""

    if decision.action not in {"direct", "delegate"}:
        raise ValueError(
            "approval request requires direct or delegate decision"
        )
    target = decision.target_agent_type
    capability = decision.capability
    if target is None or capability is None:
        raise ValueError(
            "approval request requires target Agent and capability"
        )

    return {
        "kind": "orchestration_approval",
        "action": decision.action,
        "source_agent_type": decision.source_agent_type,
        "target_agent_type": target,
        "capability": capability,
        "reason": _bounded_text(decision.reason, max_chars=500),
        "question": _bounded_text(question, max_chars=1_000),
    }


def normalize_approval_comment(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("approval comment must be a string")
    normalized = value.strip()
    if not normalized:
        return None
    return _bounded_text(normalized, max_chars=1_000)


def _bounded_text(value: str, *, max_chars: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("approval text must not be empty")
    if len(normalized) <= max_chars:
        return normalized
    suffix = " …[truncated]"
    return normalized[: max_chars - len(suffix)].rstrip() + suffix


__all__ = [
    "ApprovalAction",
    "ApprovalStatus",
    "HumanApprovalPolicy",
    "HumanApprovalResponse",
    "approval_request_payload",
    "normalize_approval_comment",
]
