from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from docker_agent.agent.protocol import AgentProtocol
from docker_agent.agent.registry import AgentRegistry

AgentBuilder = Callable[[], AgentProtocol]


class AgentBuilderAlreadyRegistered(ValueError):
    """Raised when one runtime builder is registered more than once."""


class AgentBuilderNotRegistered(LookupError):
    """Raised when a registered Agent has no runtime builder."""


class AgentFactory:
    """Create and cache runtime Agent instances by canonical Agent type."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
    ) -> None:
        self._registry = registry
        self._builders: dict[str, AgentBuilder] = {}
        self._instances: dict[str, AgentProtocol] = {}
        self._build_locks: dict[str, Lock] = {}
        self._lock = Lock()

    def register(
        self,
        agent_type: str,
        builder: AgentBuilder,
    ) -> None:
        descriptor = self._registry.get(agent_type)
        canonical = descriptor.agent_type

        with self._lock:
            if canonical in self._builders:
                raise AgentBuilderAlreadyRegistered(canonical)
            self._builders[canonical] = builder
            self._build_locks[canonical] = Lock()
            self._instances.pop(canonical, None)

    def get(self, agent_type: str) -> AgentProtocol:
        descriptor = self._registry.get(agent_type)
        canonical = descriptor.agent_type

        with self._lock:
            instance = self._instances.get(canonical)
            if instance is not None:
                return instance
            try:
                builder = self._builders[canonical]
                build_lock = self._build_locks[canonical]
            except KeyError as exc:
                raise AgentBuilderNotRegistered(canonical) from exc

        with build_lock:
            with self._lock:
                instance = self._instances.get(canonical)
                if instance is not None:
                    return instance

            instance = builder()

            with self._lock:
                self._instances[canonical] = instance
            return instance

    def invalidate(self, agent_type: str) -> bool:
        descriptor = self._registry.get(agent_type)
        canonical = descriptor.agent_type

        with self._lock:
            try:
                build_lock = self._build_locks[canonical]
            except KeyError as exc:
                raise AgentBuilderNotRegistered(canonical) from exc

        with build_lock, self._lock:
            return (
                self._instances.pop(canonical, None)
                is not None
            )

    def clear(self) -> None:
        with self._lock:
            self._instances.clear()

    def registered_types(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._builders))


def validate_factory_registration(
    *,
    registry: AgentRegistry,
    factory: AgentFactory,
) -> None:
    """Require every runtime descriptor to have exactly one builder."""

    runtime_types = {
        descriptor.agent_type
        for descriptor in registry.list()
    }
    builder_types = set(factory.registered_types())

    missing = sorted(runtime_types - builder_types)
    if missing:
        raise AgentBuilderNotRegistered(
            ", ".join(missing)
        )


__all__ = [
    "AgentBuilder",
    "AgentBuilderAlreadyRegistered",
    "AgentBuilderNotRegistered",
    "AgentFactory",
    "AgentProtocol",
    "validate_factory_registration",
]
