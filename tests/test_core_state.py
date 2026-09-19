import pytest

from docker_agent.core.evidence import Evidence, EvidenceKind
from docker_agent.core.state import AgentState, AgentStep
from docker_agent.core.tool_result import ToolErrorType, ToolResult


def _tool_result() -> ToolResult:
    return ToolResult(
        tool_name="docker_stats",
        ok=True,
        output='{"MemUsage":"64MiB"}',
        error=None,
        error_type=ToolErrorType.NONE,
        metadata={"adapter": "docker_cli"},
    )


def _evidence() -> Evidence:
    return Evidence(
        evidence_id="ev_runtime_1",
        kind=EvidenceKind.RUNTIME,
        source="docker_stats",
        content='{"MemUsage":"64MiB"}',
        ok=True,
        citation_label="[R1]",
    )


def _step() -> AgentStep:
    return AgentStep(
        index=1,
        action="tool",
        tool_name="docker_stats",
        reason="Measure current memory usage.",
        ok=True,
    )


def test_agent_state_initializes_one_turn_without_runtime_data() -> None:
    state = AgentState(question="web 现在用了多少内存？")

    assert state.question == "web 现在用了多少内存？"
    assert state.route is None
    assert state.tool_results == ()
    assert state.evidence == ()
    assert state.runtime_steps == ()
    assert state.answer is None
    assert state.errors == ()


def test_agent_state_updates_route_immutably() -> None:
    initial = AgentState(question="web 现在用了多少内存？")

    routed = initial.with_route(
        "runtime_tools",
        container_ref="web",
        use_docs=False,
    )

    assert initial.route is None
    assert routed.route == "runtime_tools"
    assert routed.container_ref == "web"
    assert routed.use_docs is False


def test_agent_state_appends_tool_result_evidence_and_step() -> None:
    initial = AgentState(question="web 现在用了多少内存？")

    updated = (
        initial.append_tool_result(_tool_result())
        .append_evidence(_evidence())
        .append_runtime_step(_step())
    )

    assert len(updated.tool_results) == 1
    assert updated.evidence[0].citation_label == "[R1]"
    assert updated.runtime_steps[0].tool_name == "docker_stats"
    assert initial.tool_results == ()


def test_agent_state_appends_error_and_answer() -> None:
    state = (
        AgentState(question="web 为什么退出？")
        .append_error("docker_logs unavailable")
        .with_answer("日志不可用，因此无法确认具体根因。")
    )

    assert state.errors == ("docker_logs unavailable",)
    assert state.answer == "日志不可用，因此无法确认具体根因。"


def test_agent_state_rejects_duplicate_evidence_labels() -> None:
    first = _evidence()
    second = Evidence(
        evidence_id="ev_runtime_2",
        kind=EvidenceKind.RUNTIME,
        source="docker_logs",
        content="error",
        ok=True,
        citation_label="[R1]",
    )

    with pytest.raises(ValueError, match="duplicate citation labels"):
        AgentState(
            question="web 为什么退出？",
            evidence=(first, second),
        )


def test_agent_state_rejects_duplicate_step_indices() -> None:
    first = _step()
    second = AgentStep(
        index=1,
        action="finish",
        tool_name=None,
        reason="Evidence is sufficient.",
        ok=None,
    )

    with pytest.raises(ValueError, match="duplicate runtime step indices"):
        AgentState(
            question="web 现在用了多少内存？",
            runtime_steps=(first, second),
        )


def test_agent_step_requires_positive_index() -> None:
    with pytest.raises(ValueError, match="index must be positive"):
        AgentStep(
            index=0,
            action="tool",
            tool_name="docker_stats",
            reason="Measure memory.",
            ok=True,
        )
