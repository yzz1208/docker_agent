from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.factory import AgentFactory
from docker_agent.agent.protocol import AgentTurnProtocol
from docker_agent.agent.registry import (
    AgentNotRegistered,
    AgentRegistry,
    AgentRegistryError,
)
from docker_agent.orchestration.decision import OrchestrationDecision
from docker_agent.orchestration.delegation import (
    AgentCapabilityIndex,
    DelegationContext,
    DelegationPolicy,
    DelegationPolicyError,
)


class OrchestrationExecutionError(RuntimeError):
    """Base error for a rejected or failed orchestration execution."""


class OrchestrationSpecialistExecutionError(OrchestrationExecutionError):
    """Raised when one selected specialist fails while handling the request."""


@dataclass(frozen=True, slots=True)
class OrchestrationExecutionResult:
    decision: OrchestrationDecision
    context: DelegationContext
    agent_type: str | None
    turn: AgentTurnProtocol | None

    @property
    def executed(self) -> bool:
        return self.turn is not None

    @property
    def current_agent_type(self) -> str | None:
        if self.agent_type is not None:
            return self.agent_type
        return self.context.current_agent_type


class DelegationExecutionService:
    """Execute one validated orchestration decision at most once."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        factory: AgentFactory,
        max_hops: int = 2,
    ) -> None:
        self._registry = registry
        self._factory = factory
        self._capabilities = AgentCapabilityIndex(registry)
        self._policy = DelegationPolicy(
            registry=registry,
            max_hops=max_hops,
        )

    def execute(
        self,
        question: str,
        *,
        decision: OrchestrationDecision,
        context: DelegationContext | None = None,
    ) -> OrchestrationExecutionResult:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be empty")

        active_context = context or DelegationContext(
            original_query=normalized_question
        )
        self._validate_common(decision, active_context)

        if decision.action == "clarify":
            self._validate_clarify(decision)
            return OrchestrationExecutionResult(
                decision=decision,
                context=active_context,
                agent_type=None,
                turn=None,
            )

        if decision.action == "direct":
            target = self._validate_direct(decision, active_context)
            next_context = active_context
        else:
            target, next_context = self._validate_delegate(
                decision,
                active_context,
            )

        try:
            agent = self._factory.get(target)
            turn = agent.handle(normalized_question)
        except Exception as exc:
            raise OrchestrationSpecialistExecutionError(
                f"Agent {target!r} failed during orchestration execution"
            ) from exc

        return OrchestrationExecutionResult(
            decision=decision,
            context=next_context,
            agent_type=target,
            turn=turn,
        )

    def _validate_common(
        self,
        decision: OrchestrationDecision,
        context: DelegationContext,
    ) -> None:
        if decision.action not in {"clarify", "direct", "delegate"}:
            raise OrchestrationExecutionError(
                f"unsupported orchestration action: {decision.action!r}"
            )
        if not decision.reason.strip():
            raise OrchestrationExecutionError(
                "decision reason must not be empty"
            )

        current = context.current_agent_type
        if current is not None:
            if decision.source_agent_type is None:
                raise OrchestrationExecutionError(
                    "decision source is required when context has an owner"
                )
            try:
                source = self._registry.get(
                    decision.source_agent_type
                ).agent_type
            except AgentRegistryError as exc:
                raise OrchestrationExecutionError(str(exc)) from exc
            if source != current:
                raise OrchestrationExecutionError(
                    f"decision source must match current context owner "
                    f"{current!r}"
                )

    def _validate_clarify(
        self,
        decision: OrchestrationDecision,
    ) -> None:
        if not decision.clarification:
            raise OrchestrationExecutionError(
                "clarify decision requires a clarification question"
            )
        if (
            decision.target_agent_type is not None
            or decision.capability is not None
        ):
            raise OrchestrationExecutionError(
                "clarify decision must not select an Agent or capability"
            )

    def _validate_direct(
        self,
        decision: OrchestrationDecision,
        context: DelegationContext,
    ) -> str:
        target, capability = self._validated_target(decision)
        source = decision.source_agent_type
        current = context.current_agent_type

        if source is not None and target != source:
            raise OrchestrationExecutionError(
                "direct decision cannot change the source Agent"
            )
        if current is not None and target != current:
            raise OrchestrationExecutionError(
                "direct decision cannot change the current context owner"
            )

        self._require_capability(target, capability)
        return target

    def _validate_delegate(
        self,
        decision: OrchestrationDecision,
        context: DelegationContext,
    ) -> tuple[str, DelegationContext]:
        target, capability = self._validated_target(decision)
        source = decision.source_agent_type
        if source is None:
            raise OrchestrationExecutionError(
                "delegate decision requires a source Agent"
            )

        try:
            next_context = self._policy.delegate(
                context,
                source_agent_type=source,
                target_agent_type=target,
                capability=capability,
                reason=decision.reason,
            )
        except DelegationPolicyError as exc:
            raise OrchestrationExecutionError(str(exc)) from exc

        return target, next_context

    def _validated_target(
        self,
        decision: OrchestrationDecision,
    ) -> tuple[str, str]:
        if decision.target_agent_type is None:
            raise OrchestrationExecutionError(
                f"{decision.action} decision requires target_agent_type"
            )
        if decision.capability is None:
            raise OrchestrationExecutionError(
                f"{decision.action} decision requires capability"
            )
        if decision.clarification is not None:
            raise OrchestrationExecutionError(
                f"{decision.action} decision must not include clarification"
            )

        try:
            target = self._registry.get(
                decision.target_agent_type
            ).agent_type
        except AgentNotRegistered as exc:
            raise OrchestrationExecutionError(
                f"target Agent is not registered: "
                f"{decision.target_agent_type!r}"
            ) from exc
        except AgentRegistryError as exc:
            raise OrchestrationExecutionError(str(exc)) from exc

        capability = _canonical_capability(decision.capability)
        return target, capability

    def _require_capability(
        self,
        target_agent_type: str,
        capability: str,
    ) -> None:
        try:
            supported = self._capabilities.supports(
                target_agent_type,
                capability,
            )
        except AgentRegistryError as exc:
            raise OrchestrationExecutionError(str(exc)) from exc
        if not supported:
            raise OrchestrationExecutionError(
                f"Agent {target_agent_type!r} does not expose "
                f"capability {capability!r}"
            )


def _canonical_capability(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        raise OrchestrationExecutionError(
            "capability must not be empty"
        )
    return normalized


__all__ = [
    "DelegationExecutionService",
    "OrchestrationExecutionError",
    "OrchestrationExecutionResult",
    "OrchestrationSpecialistExecutionError",
]
