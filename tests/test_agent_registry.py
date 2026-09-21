import pytest

from docker_agent.agent.registry import (
    DOCKER_SUPPORT_DESCRIPTOR,
    AgentAlreadyRegistered,
    AgentDescriptor,
    AgentNotRegistered,
    AgentRegistry,
    AgentRegistryError,
    build_agent_registry,
)


def _descriptor(agent_type: str, display_name: str) -> AgentDescriptor:
    return AgentDescriptor(
        agent_type=agent_type,
        display_name=display_name,
        description=f"{display_name} description",
        capabilities=("chat",),
        knowledge_sources=(),
        toolsets=(),
        worker_roles=(),
        configuration_schema=(),
    )


def test_default_registry_contains_docker_support_descriptor() -> None:
    registry = build_agent_registry()

    descriptor = registry.get("docker_support")

    assert descriptor is DOCKER_SUPPORT_DESCRIPTOR
    assert descriptor.display_name == "Docker Support"
    assert descriptor.capabilities == (
        "chat",
        "documentation_qa",
        "runtime_diagnostics",
        "multi_agent_supervision",
    )
    assert descriptor.knowledge_sources == ("docker_docs",)
    assert descriptor.toolsets == ("docker_read_only",)
    assert descriptor.worker_roles == (
        "knowledge",
        "runtime",
        "diagnosis",
    )


def test_registry_lookup_normalizes_external_agent_type() -> None:
    registry = build_agent_registry()

    descriptor = registry.get("  Docker-Support  ")

    assert descriptor.agent_type == "docker_support"
    assert registry.contains("DOCKER-SUPPORT") is True


def test_registry_lists_descriptors_deterministically() -> None:
    registry = AgentRegistry(
        (
            _descriptor("zeta_agent", "Zeta"),
            _descriptor("alpha_agent", "Alpha"),
        )
    )

    assert [
        descriptor.agent_type
        for descriptor in registry.list()
    ] == [
        "alpha_agent",
        "zeta_agent",
    ]


def test_registry_rejects_duplicate_agent_type() -> None:
    registry = AgentRegistry((_descriptor("alpha", "Alpha"),))

    with pytest.raises(AgentAlreadyRegistered):
        registry.register(_descriptor("alpha", "Duplicate"))


def test_registry_rejects_unknown_agent_type() -> None:
    registry = build_agent_registry()

    with pytest.raises(AgentNotRegistered):
        registry.get("future_agent")


def test_descriptor_requires_normalized_agent_type() -> None:
    with pytest.raises(
        AgentRegistryError,
        match="already be normalized",
    ):
        _descriptor("Future-Agent", "Future")


def test_descriptor_rejects_duplicate_metadata_labels() -> None:
    with pytest.raises(
        AgentRegistryError,
        match="capabilities must not contain duplicates",
    ):
        AgentDescriptor(
            agent_type="future_agent",
            display_name="Future",
            description="Future description",
            capabilities=("chat", "chat"),
            knowledge_sources=(),
            toolsets=(),
            worker_roles=(),
            configuration_schema=(),
        )
