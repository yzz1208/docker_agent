from __future__ import annotations

from dataclasses import dataclass


class AgentRegistryError(ValueError):
    """Base error for invalid Agent registry operations."""


class AgentAlreadyRegistered(AgentRegistryError):
    """Raised when one Agent type is registered more than once."""


class AgentNotRegistered(AgentRegistryError):
    """Raised when a runtime Agent type is not registered."""


def _normalize_agent_type(agent_type: str) -> str:
    if not isinstance(agent_type, str):
        raise AgentRegistryError(
            "agent_type must be a string"
        )

    normalized = agent_type.strip().lower().replace("-", "_")
    if not normalized:
        raise AgentRegistryError(
            "agent_type must not be empty"
        )

    allowed = set(
        "abcdefghijklmnopqrstuvwxyz0123456789_"
    )
    if any(character not in allowed for character in normalized):
        raise AgentRegistryError(
            "agent_type may contain only lowercase letters, "
            "numbers, underscores, and hyphens"
        )
    return normalized


def _validate_labels(
    values: tuple[str, ...],
    *,
    field: str,
) -> None:
    if len(set(values)) != len(values):
        raise AgentRegistryError(
            f"{field} must not contain duplicates"
        )
    for value in values:
        if not value.strip():
            raise AgentRegistryError(
                f"{field} must not contain empty values"
            )

@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """Immutable runtime metadata for one supported Agent type."""

    agent_type: str
    display_name: str
    description: str
    capabilities: tuple[str, ...]
    knowledge_sources: tuple[str, ...]
    toolsets: tuple[str, ...]
    worker_roles: tuple[str, ...]
    configuration_groups: tuple[str, ...]
    default_enabled: bool = True

    def __post_init__(self) -> None:
        normalized_type = _normalize_agent_type(self.agent_type)
        if normalized_type != self.agent_type:
            raise AgentRegistryError(
                "agent_type must already be normalized"
            )
        if not self.display_name.strip():
            raise AgentRegistryError(
                "display_name must not be empty"
            )
        if not self.description.strip():
            raise AgentRegistryError(
                "description must not be empty"
            )

        for label, values in {
            "capabilities": self.capabilities,
            "knowledge_sources": self.knowledge_sources,
            "toolsets": self.toolsets,
            "worker_roles": self.worker_roles,
            "configuration_groups": self.configuration_groups,
        }.items():
            _validate_labels(values, field=label)


class AgentRegistry:
    """In-process catalog of runtime-supported Agent types."""

    def __init__(
        self,
        descriptors: tuple[AgentDescriptor, ...] = (),
    ) -> None:
        self._descriptors: dict[str, AgentDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(
        self,
        descriptor: AgentDescriptor,
    ) -> None:
        agent_type = descriptor.agent_type
        if agent_type in self._descriptors:
            raise AgentAlreadyRegistered(agent_type)
        self._descriptors[agent_type] = descriptor

    def get(self, agent_type: str) -> AgentDescriptor:
        normalized = _normalize_agent_type(agent_type)
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            raise AgentNotRegistered(normalized) from exc

    def list(self) -> tuple[AgentDescriptor, ...]:
        return tuple(
            self._descriptors[key]
            for key in sorted(self._descriptors)
        )

    def contains(self, agent_type: str) -> bool:
        try:
            normalized = _normalize_agent_type(agent_type)
        except AgentRegistryError:
            return False
        return normalized in self._descriptors


DOCKER_SUPPORT_DESCRIPTOR = AgentDescriptor(
    agent_type="docker_support",
    display_name="Docker Support",
    description=(
        "Docker technical support Agent with documentation retrieval, "
        "read-only runtime diagnostics, and LangGraph worker orchestration."
    ),
    capabilities=(
        "chat",
        "documentation_qa",
        "runtime_diagnostics",
        "multi_agent_supervision",
    ),
    knowledge_sources=("docker_docs",),
    toolsets=("docker_read_only",),
    worker_roles=(
        "knowledge",
        "runtime",
        "diagnosis",
    ),
    configuration_groups=(
        "model_settings",
        "retrieval_settings",
        "runtime_settings",
    ),
)


def build_agent_registry() -> AgentRegistry:
    """Build the default runtime Agent registry."""

    return AgentRegistry((DOCKER_SUPPORT_DESCRIPTOR,))


