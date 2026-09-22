import pytest

from docker_agent.core.evidence import runtime_tool_result_to_evidence
from docker_agent.core.state import AgentState, AgentStep
from docker_agent.core.tool_result import ToolErrorType, ToolResult
from docker_agent.multi_agent.execution import (
    WorkerExecutionRecord,
    build_worker_execution_record,
)


def test_worker_execution_record_summarizes_state_deltas() -> None:
    before = AgentState(question="web 现在用了多少内存？")
    tool_result = ToolResult(
        tool_name="docker_stats",
        ok=True,
        output='{"MemUsage":"128MiB / 2GiB"}',
        error=None,
        error_type=ToolErrorType.NONE,
        metadata={
            "adapter": "docker_cli",
            "command": ("docker", "stats", "--no-stream", "web"),
            "returncode": 0,
        },
    )
    after = before.append_tool_result(tool_result)
    after = after.append_evidence(
        runtime_tool_result_to_evidence(
            tool_result,
            index=1,
        )
    )
    after = after.append_runtime_step(
        AgentStep(
            index=1,
            action="tool",
            tool_name="docker_stats",
            reason="measure memory",
            ok=True,
        )
    )

    record = build_worker_execution_record(
        index=1,
        role="runtime",
        before=before,
        after=after,
    )

    assert record.index == 1
    assert record.role == "runtime"
    assert record.tool_results_added == 1
    assert record.evidence_added == 1
    assert record.runtime_steps_added == 1
    assert record.answer_created is False


def test_worker_execution_record_detects_answer_creation() -> None:
    before = AgentState(question="Docker volume 是什么？")
    after = before.with_answer("Docker volume 由 Docker 管理。[1]")

    record = build_worker_execution_record(
        index=2,
        role="diagnosis",
        before=before,
        after=after,
    )

    assert record.answer_created is True
    assert record.tool_results_added == 0
    assert record.evidence_added == 0
    assert record.runtime_steps_added == 0


def test_worker_execution_record_rejects_invalid_index() -> None:
    with pytest.raises(
        ValueError,
        match="WorkerExecutionRecord index must be positive",
    ):
        WorkerExecutionRecord(
            index=0,
            role="knowledge",
            tool_results_added=0,
            evidence_added=0,
            runtime_steps_added=0,
            answer_created=False,
        )
