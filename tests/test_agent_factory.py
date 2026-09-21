import pytest

from docker_agent.agent.factory import (
    AgentBuilderAlreadyRegistered,
    AgentBuilderNotRegistered,
    AgentFactory,
    validate_factory_registration,
)
from docker_agent.agent.protocol import AgentTurnProtocol
from docker_agent.agent.registry import (
    AgentDescriptor,
    AgentRegistry,
)


class DummyAgent:
    def __init__(self, name: str) -> None:
        self.name = name

    def handle(self, question: str) -> AgentTurnProtocol:
        raise NotImplementedError(question)


def _descriptor(agent_type: str) -> AgentDescriptor:
    return AgentDescriptor(
        agent_type=agent_type,
        display_name=agent_type,
        description=f"{agent_type} description",
        capabilities=("chat",),
        knowledge_sources=(),
        toolsets=(),
        worker_roles=(),
        configuration_groups=(),
    )


def test_agent_factory_caches_one_instance_per_canonical_type() -> None:
    registry = AgentRegistry((_descriptor("alpha_agent"),))
    factory = AgentFactory(registry=registry)
    build_count = 0

    def build() -> DummyAgent:
        nonlocal build_count
        build_count += 1
        return DummyAgent("alpha")

    factory.register("alpha_agent", build)

    first = factory.get("Alpha-Agent")
    second = factory.get("alpha_agent")

    assert first is second
    assert build_count == 1


def test_agent_factory_invalidate_rebuilds_only_target_agent() -> None:
    registry = AgentRegistry(
        (
            _descriptor("alpha_agent"),
            _descriptor("beta_agent"),
        )
    )
    factory = AgentFactory(registry=registry)
    counts = {
        "alpha": 0,
        "beta": 0,
    }

    def build_alpha() -> DummyAgent:
        counts["alpha"] += 1
        return DummyAgent("alpha")

    def build_beta() -> DummyAgent:
        counts["beta"] += 1
        return DummyAgent("beta")

    factory.register("alpha_agent", build_alpha)
    factory.register("beta_agent", build_beta)

    alpha_first = factory.get("alpha_agent")
    beta_first = factory.get("beta_agent")

    assert factory.invalidate("alpha_agent") is True
    assert factory.invalidate("alpha_agent") is False

    alpha_second = factory.get("alpha_agent")
    beta_second = factory.get("beta_agent")

    assert alpha_second is not alpha_first
    assert beta_second is beta_first
    assert counts == {
        "alpha": 2,
        "beta": 1,
    }


def test_agent_factory_rejects_duplicate_builder() -> None:
    registry = AgentRegistry((_descriptor("alpha_agent"),))
    factory = AgentFactory(registry=registry)
    factory.register(
        "alpha_agent",
        lambda: DummyAgent("alpha"),
    )

    with pytest.raises(AgentBuilderAlreadyRegistered):
        factory.register(
            "alpha_agent",
            lambda: DummyAgent("duplicate"),
        )


def test_agent_factory_reports_missing_builder() -> None:
    registry = AgentRegistry((_descriptor("alpha_agent"),))
    factory = AgentFactory(registry=registry)

    with pytest.raises(AgentBuilderNotRegistered):
        factory.get("alpha_agent")


def test_factory_registration_requires_builder_for_every_descriptor() -> None:
    registry = AgentRegistry(
        (
            _descriptor("alpha_agent"),
            _descriptor("beta_agent"),
        )
    )
    factory = AgentFactory(registry=registry)
    factory.register(
        "alpha_agent",
        lambda: DummyAgent("alpha"),
    )

    with pytest.raises(
        AgentBuilderNotRegistered,
        match="beta_agent",
    ):
        validate_factory_registration(
            registry=registry,
            factory=factory,
        )

    factory.register(
        "beta_agent",
        lambda: DummyAgent("beta"),
    )
    validate_factory_registration(
        registry=registry,
        factory=factory,
    )


def test_agent_factory_clear_rebuilds_all_instances() -> None:
    registry = AgentRegistry((_descriptor("alpha_agent"),))
    factory = AgentFactory(registry=registry)
    factory.register(
        "alpha_agent",
        lambda: DummyAgent("alpha"),
    )

    first = factory.get("alpha_agent")
    factory.clear()
    second = factory.get("alpha_agent")

    assert second is not first
