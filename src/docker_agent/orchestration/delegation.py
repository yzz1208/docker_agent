from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.registry import (
    AgentDescriptor,
    AgentRegistry,
)


class DelegationPolicyError(ValueError):
    """Base error for invalid cross-Agent delegation."""


class DelegationCapabilityUnavailable(DelegationPolicyError):
    """Raised when the target Agent does not expose the requested capability."""


class DelegationHopLimitExceeded(DelegationPolicyError):
    """Raised when a delegation would exceed the configured hop limit."""


class DelegationLoopDetected(DelegationPolicyError):
    """Raised when delegation would revisit an Agent in the same trace."""


class DelegationSourceMismatch(DelegationPolicyError):
    """Raised when a handoff source does not match the current trace owner."""


@dataclass(frozen=True, slots=True)
class AgentHandoff:
    index: int
    source_agent_type: str | None
    target_agent_type: str
    capability: str
    reason: str


@dataclass(frozen=True, slots=True)
class DelegationContext:
    original_query: str
    handoffs: tuple[AgentHandoff, ...] = ()

    def __post_init__(self) -> None:
        if not self.original_query.strip():
            raise DelegationPolicyError(
                "original_query must not be empty"
            )

    @property
    def hop_count(self) -> int:
        return len(self.handoffs)

    @property
    def current_agent_type(self) -> str | None:
        if not self.handoffs:
            return None
        return self.handoffs[-1].target_agent_type

    @property
    def visited_agents(self) -> tuple[str, ...]:
        visited: list[str] = []
        for handoff in self.handoffs:
            if (
                handoff.source_agent_type is not None
                and handoff.source_agent_type not in visited
            ):
                visited.append(handoff.source_agent_type)
            if handoff.target_agent_type not in visited:
                visited.append(handoff.target_agent_type)
        return tuple(visited)

    def append(self, handoff: AgentHandoff) -> DelegationContext:
        expected_index = self.hop_count + 1
        if handoff.index != expected_index:
            raise DelegationPolicyError(
                "handoff index must continue the delegation trace"
            )
        return DelegationContext(
            original_query=self.original_query,
            handoffs=(*self.handoffs, handoff),
        )


class AgentCapabilityIndex:
    """Deterministic capability lookup over the runtime Agent registry."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        by_capability: dict[str, list[AgentDescriptor]] = {}

        for descriptor in registry.list():
            for capability in descriptor.capabilities:
                normalized = _normalize_capability(capability)
                by_capability.setdefault(normalized, []).append(
                    descriptor
                )

        self._by_capability = {
            capability: tuple(
                sorted(
                    descriptors,
                    key=lambda descriptor: descriptor.agent_type,
                )
            )
            for capability, descriptors in by_capability.items()
        }

    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_capability))

    def agents_for(
        self,
        capability: str,
    ) -> tuple[AgentDescriptor, ...]:
        normalized = _normalize_capability(capability)
        return self._by_capability.get(normalized, ())

    def supports(
        self,
        agent_type: str,
        capability: str,
    ) -> bool:
        descriptor = self._registry.get(agent_type)
        normalized = _normalize_capability(capability)
        return any(
            _normalize_capability(item) == normalized
            for item in descriptor.capabilities
        )


class DelegationPolicy:
    """Validate bounded, acyclic Agent-to-Agent handoffs."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        max_hops: int = 2,
        allow_revisit: bool = False,
    ) -> None:
        if max_hops <= 0:
            raise ValueError("max_hops must be positive")

        self._registry = registry
        self._capabilities = AgentCapabilityIndex(registry)
        self.max_hops = max_hops
        self.allow_revisit = allow_revisit

    def delegate(
        self,
        context: DelegationContext,
        *,
        source_agent_type: str | None,
        target_agent_type: str,
        capability: str,
        reason: str,
    ) -> DelegationContext:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise DelegationPolicyError(
                "delegation reason must not be empty"
            )

        if context.hop_count >= self.max_hops:
            raise DelegationHopLimitExceeded(
                f"delegation hop limit {self.max_hops} reached"
            )

        source = self._canonical_source(source_agent_type)
        target = self._registry.get(target_agent_type).agent_type
        normalized_capability = _normalize_capability(capability)

        self._validate_source_continuity(
            context,
            source_agent_type=source,
        )

        if source == target:
            raise DelegationLoopDetected(
                "an Agent cannot delegate to itself"
            )

        if (
            not self.allow_revisit
            and target in context.visited_agents
        ):
            raise DelegationLoopDetected(
                f"Agent {target!r} already appears in delegation trace"
            )

        if not self._capabilities.supports(
            target,
            normalized_capability,
        ):
            raise DelegationCapabilityUnavailable(
                f"Agent {target!r} does not expose capability "
                f"{normalized_capability!r}"
            )

        handoff = AgentHandoff(
            index=context.hop_count + 1,
            source_agent_type=source,
            target_agent_type=target,
            capability=normalized_capability,
            reason=normalized_reason,
        )
        return context.append(handoff)

    def candidates(
        self,
        capability: str,
        *,
        exclude_agent_types: tuple[str, ...] = (),
    ) -> tuple[AgentDescriptor, ...]:
        excluded = {
            self._registry.get(agent_type).agent_type
            for agent_type in exclude_agent_types
        }
        return tuple(
            descriptor
            for descriptor in self._capabilities.agents_for(capability)
            if descriptor.agent_type not in excluded
        )

    def _canonical_source(
        self,
        source_agent_type: str | None,
    ) -> str | None:
        if source_agent_type is None:
            return None
        return self._registry.get(source_agent_type).agent_type

    def _validate_source_continuity(
        self,
        context: DelegationContext,
        *,
        source_agent_type: str | None,
    ) -> None:
        current = context.current_agent_type
        if current is None:
            return

        if source_agent_type != current:
            raise DelegationSourceMismatch(
                f"delegation source must be current Agent {current!r}"
            )


def _normalize_capability(capability: str) -> str:
    if not isinstance(capability, str):
        raise DelegationPolicyError(
            "capability must be a string"
        )

    normalized = capability.strip().lower().replace("-", "_")
    if not normalized:
        raise DelegationPolicyError(
            "capability must not be empty"
        )

    allowed = set(
        "abcdefghijklmnopqrstuvwxyz0123456789_"
    )
    if any(character not in allowed for character in normalized):
        raise DelegationPolicyError(
            "capability may contain only lowercase letters, "
            "numbers, underscores, and hyphens"
        )
    return normalized


__all__ = [
    "AgentCapabilityIndex",
    "AgentHandoff",
    "DelegationCapabilityUnavailable",
    "DelegationContext",
    "DelegationHopLimitExceeded",
    "DelegationLoopDetected",
    "DelegationPolicy",
    "DelegationPolicyError",
    "DelegationSourceMismatch",
]
