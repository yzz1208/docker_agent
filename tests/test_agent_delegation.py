import pytest

from docker_agent.agent.registry import build_agent_registry
from docker_agent.orchestration import (
    AgentCapabilityIndex,
    DelegationCapabilityUnavailable,
    DelegationContext,
    DelegationHopLimitExceeded,
    DelegationLoopDetected,
    DelegationPolicy,
    DelegationPolicyError,
    DelegationSourceMismatch,
)


def test_capability_index_lists_agents_deterministically() -> None:
    registry = build_agent_registry()
    index = AgentCapabilityIndex(registry)

    chat_agents = index.agents_for("chat")

    assert [
        descriptor.agent_type
        for descriptor in chat_agents
    ] == [
        "docker_support",
        "infrastructure_troubleshooter",
    ]
    assert [
        descriptor.agent_type
        for descriptor in index.agents_for("runtime-diagnostics")
    ] == [
        "docker_support",
    ]
    assert [
        descriptor.agent_type
        for descriptor in index.agents_for("incident_triage")
    ] == [
        "infrastructure_troubleshooter",
    ]
    assert index.agents_for("missing_capability") == ()


def test_capability_index_checks_agent_support() -> None:
    registry = build_agent_registry()
    index = AgentCapabilityIndex(registry)

    assert index.supports(
        "Docker-Support",
        "runtime-diagnostics",
    )
    assert not index.supports(
        "infrastructure_troubleshooter",
        "runtime_diagnostics",
    )


def test_delegation_policy_records_canonical_handoff_trace() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(
        registry=registry,
        max_hops=3,
    )
    context = DelegationContext(
        original_query="The API is failing after a container restart."
    )

    delegated = policy.delegate(
        context,
        source_agent_type="Docker-Support",
        target_agent_type="Infrastructure-Troubleshooter",
        capability="incident-triage",
        reason="The failure is broader than one container.",
    )

    assert delegated.hop_count == 1
    assert delegated.current_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert delegated.visited_agents == (
        "docker_support",
        "infrastructure_troubleshooter",
    )
    assert delegated.handoffs[0].index == 1
    assert delegated.handoffs[0].source_agent_type == "docker_support"
    assert delegated.handoffs[0].target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert delegated.handoffs[0].capability == "incident_triage"


def test_platform_dispatch_can_start_without_source_agent() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)

    delegated = policy.delegate(
        DelegationContext(original_query="Why is checkout returning 503?"),
        source_agent_type=None,
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="The request is an incident triage problem.",
    )

    assert delegated.handoffs[0].source_agent_type is None
    assert delegated.current_agent_type == (
        "infrastructure_troubleshooter"
    )


def test_delegation_rejects_capability_missing_from_target() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)

    with pytest.raises(
        DelegationCapabilityUnavailable,
        match="runtime_diagnostics",
    ):
        policy.delegate(
            DelegationContext(original_query="Inspect the container."),
            source_agent_type=None,
            target_agent_type="infrastructure_troubleshooter",
            capability="runtime_diagnostics",
            reason="Need runtime diagnostics.",
        )


def test_delegation_rejects_self_handoff() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)

    with pytest.raises(
        DelegationLoopDetected,
        match="cannot delegate to itself",
    ):
        policy.delegate(
            DelegationContext(original_query="Inspect Docker."),
            source_agent_type="docker_support",
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
            reason="Stay on the same Agent.",
        )


def test_delegation_rejects_return_to_visited_source() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(
        registry=registry,
        max_hops=3,
    )
    context = policy.delegate(
        DelegationContext(original_query="Investigate an incident."),
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        reason="Escalate from container detail to service incident.",
    )

    with pytest.raises(
        DelegationLoopDetected,
        match="already appears",
    ):
        policy.delegate(
            context,
            source_agent_type="infrastructure_troubleshooter",
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
            reason="Return to the original Agent.",
        )


def test_delegation_requires_source_trace_continuity() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(
        registry=registry,
        max_hops=3,
    )
    context = policy.delegate(
        DelegationContext(original_query="Investigate an incident."),
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        reason="Start with container runtime evidence.",
    )

    with pytest.raises(
        DelegationSourceMismatch,
        match="docker_support",
    ):
        policy.delegate(
            context,
            source_agent_type="infrastructure_troubleshooter",
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
            reason="Invalid trace source.",
        )


def test_delegation_enforces_hop_limit() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(
        registry=registry,
        max_hops=1,
    )
    context = policy.delegate(
        DelegationContext(original_query="Investigate an incident."),
        source_agent_type=None,
        target_agent_type="docker_support",
        capability="runtime_diagnostics",
        reason="Start with Docker evidence.",
    )

    with pytest.raises(
        DelegationHopLimitExceeded,
        match="hop limit 1",
    ):
        policy.delegate(
            context,
            source_agent_type="docker_support",
            target_agent_type="infrastructure_troubleshooter",
            capability="incident_triage",
            reason="Escalate to service incident triage.",
        )


def test_delegation_candidates_can_exclude_current_agent() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)

    candidates = policy.candidates(
        "chat",
        exclude_agent_types=("docker_support",),
    )

    assert [
        descriptor.agent_type
        for descriptor in candidates
    ] == [
        "infrastructure_troubleshooter",
    ]


def test_delegation_requires_nonempty_query_and_reason() -> None:
    registry = build_agent_registry()
    policy = DelegationPolicy(registry=registry)

    with pytest.raises(
        DelegationPolicyError,
        match="original_query",
    ):
        DelegationContext(original_query="   ")

    with pytest.raises(
        DelegationPolicyError,
        match="reason",
    ):
        policy.delegate(
            DelegationContext(original_query="Investigate."),
            source_agent_type=None,
            target_agent_type="docker_support",
            capability="runtime_diagnostics",
            reason="   ",
        )
