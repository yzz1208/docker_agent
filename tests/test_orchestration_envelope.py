from __future__ import annotations

from dataclasses import dataclass

import pytest

from docker_agent.orchestration import (
    CrossAgentEnvelopeError,
    SpecialistResultEnvelope,
    build_cross_agent_context_envelope,
    build_specialist_result_envelope,
)


@dataclass(frozen=True, slots=True)
class PublicAnswer:
    answer: str
    runtime_sources: tuple[str, ...] = ("RAW_RUNTIME_SECRET",)
    doc_sources: tuple[str, ...] = ("RAW_DOC_SECRET",)


@dataclass(frozen=True, slots=True)
class PublicDecision:
    route: str
    reason: str
    clarification: str | None = None
    use_docs: bool = False


@dataclass(frozen=True, slots=True)
class TurnWithPrivateState:
    decision: PublicDecision
    answer: PublicAnswer | None
    needs_clarification: bool
    system_prompt: str = "PRIVATE_SYSTEM_PROMPT"
    raw_tool_output: str = "PRIVATE_RAW_TOOL_OUTPUT"
    worker_state: str = "PRIVATE_WORKER_STATE"


def test_specialist_result_projects_only_public_turn_fields() -> None:
    turn = TurnWithPrivateState(
        decision=PublicDecision(
            route="runtime_tools",
            reason="runtime evidence collected",
        ),
        answer=PublicAnswer(
            answer="web-1 is running and memory usage is stable.",
        ),
        needs_clarification=False,
    )

    result = build_specialist_result_envelope(
        agent_type="Docker-Support",
        turn=turn,  # type: ignore[arg-type]
    )

    assert result.agent_type == "docker_support"
    assert result.route == "runtime_tools"
    assert result.summary == (
        "web-1 is running and memory usage is stable."
    )
    public_text = repr(result)
    assert "PRIVATE_SYSTEM_PROMPT" not in public_text
    assert "PRIVATE_RAW_TOOL_OUTPUT" not in public_text
    assert "PRIVATE_WORKER_STATE" not in public_text
    assert "RAW_RUNTIME_SECRET" not in public_text
    assert "RAW_DOC_SECRET" not in public_text


def test_specialist_result_keeps_only_clarification_for_pending_turn() -> None:
    turn = TurnWithPrivateState(
        decision=PublicDecision(
            route="clarify",
            reason="container name missing",
            clarification="请提供容器名称。",
        ),
        answer=None,
        needs_clarification=True,
    )

    result = build_specialist_result_envelope(
        agent_type="docker_support",
        turn=turn,  # type: ignore[arg-type]
    )

    assert result.needs_clarification is True
    assert result.clarification == "请提供容器名称。"
    assert result.summary is None


def test_specialist_result_summary_is_bounded() -> None:
    turn = TurnWithPrivateState(
        decision=PublicDecision(
            route="triage",
            reason="incident facts available",
        ),
        answer=PublicAnswer(answer="x" * 100),
        needs_clarification=False,
    )

    result = build_specialist_result_envelope(
        agent_type="infrastructure_troubleshooter",
        turn=turn,  # type: ignore[arg-type]
        max_summary_chars=32,
    )

    assert result.summary is not None
    assert len(result.summary) <= 32
    assert result.summary.endswith("…[truncated]")


def test_cross_agent_context_normalizes_explicit_allowlisted_fields() -> None:
    prior = SpecialistResultEnvelope(
        agent_type="docker_support",
        route="runtime_tools",
        reason="container checked",
        needs_clarification=False,
        clarification=None,
        summary="Container looks healthy from the checked runtime facts.",
    )

    envelope = build_cross_agent_context_envelope(
        original_query="  checkout 服务持续失败  ",
        current_user_message="  继续分析服务级 503  ",
        explicit_user_clarification="  影响 production  ",
        source_agent_type="Docker-Support",
        target_agent_type="Infrastructure-Troubleshooter",
        capability="incident-triage",
        handoff_reason="  broader than one container  ",
        handoff_index=1,
        prior_specialist_result=prior,
    )

    assert envelope.original_query == "checkout 服务持续失败"
    assert envelope.current_user_message == "继续分析服务级 503"
    assert envelope.explicit_user_clarification == "影响 production"
    assert envelope.source_agent_type == "docker_support"
    assert envelope.target_agent_type == (
        "infrastructure_troubleshooter"
    )
    assert envelope.capability == "incident_triage"
    assert envelope.handoff_reason == "broader than one container"


def test_rendered_target_input_contains_no_private_turn_state() -> None:
    prior_turn = TurnWithPrivateState(
        decision=PublicDecision(
            route="runtime_tools",
            reason="runtime checked",
        ),
        answer=PublicAnswer(answer="Public runtime conclusion."),
        needs_clarification=False,
    )
    prior = build_specialist_result_envelope(
        agent_type="docker_support",
        turn=prior_turn,  # type: ignore[arg-type]
    )
    envelope = build_cross_agent_context_envelope(
        original_query="why is checkout failing?",
        current_user_message="container is healthy, continue triage",
        explicit_user_clarification=None,
        source_agent_type="docker_support",
        target_agent_type="infrastructure_troubleshooter",
        capability="incident_triage",
        handoff_reason="service-level failure remains",
        handoff_index=1,
        prior_specialist_result=prior,
    )

    rendered = envelope.render_for_target()

    assert "Public runtime conclusion." in rendered
    assert "PRIVATE_SYSTEM_PROMPT" not in rendered
    assert "PRIVATE_RAW_TOOL_OUTPUT" not in rendered
    assert "PRIVATE_WORKER_STATE" not in rendered
    assert "RAW_RUNTIME_SECRET" not in rendered
    assert "RAW_DOC_SECRET" not in rendered
    assert "credentials" in rendered


def test_prior_specialist_result_must_match_source_agent() -> None:
    prior = SpecialistResultEnvelope(
        agent_type="infrastructure_troubleshooter",
        route="triage",
        reason="triaged",
        needs_clarification=False,
        clarification=None,
        summary="Public summary.",
    )

    with pytest.raises(
        CrossAgentEnvelopeError,
        match="must belong to the source Agent",
    ):
        build_cross_agent_context_envelope(
            original_query="service failure",
            current_user_message="continue",
            explicit_user_clarification=None,
            source_agent_type="docker_support",
            target_agent_type="infrastructure_troubleshooter",
            capability="incident_triage",
            handoff_reason="delegate",
            handoff_index=1,
            prior_specialist_result=prior,
        )


def test_direct_dataclass_construction_requires_canonical_identity() -> None:
    with pytest.raises(
        CrossAgentEnvelopeError,
        match="agent_type must be canonical",
    ):
        SpecialistResultEnvelope(
            agent_type="Docker-Support",
            route="docs_only",
            reason="docs",
            needs_clarification=False,
            clarification=None,
            summary="Public summary.",
        )
