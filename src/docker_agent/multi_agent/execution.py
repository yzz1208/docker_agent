from __future__ import annotations

from dataclasses import dataclass

from docker_agent.core.state import AgentState
from docker_agent.multi_agent.supervisor import WorkerRole


@dataclass(frozen=True, slots=True)
class WorkerExecutionRecord:
    """Compact, serializable summary of one completed worker execution."""

    index: int
    role: WorkerRole
    tool_results_added: int
    evidence_added: int
    runtime_steps_added: int
    answer_created: bool

    def __post_init__(self) -> None:
        if self.index <= 0:
            raise ValueError("WorkerExecutionRecord index must be positive")
        if self.tool_results_added < 0:
            raise ValueError("tool_results_added must not be negative")
        if self.evidence_added < 0:
            raise ValueError("evidence_added must not be negative")
        if self.runtime_steps_added < 0:
            raise ValueError("runtime_steps_added must not be negative")


def build_worker_execution_record(
    *,
    index: int,
    role: WorkerRole,
    before: AgentState,
    after: AgentState,
) -> WorkerExecutionRecord:
    """Describe what one worker added without copying raw evidence or tool output."""

    return WorkerExecutionRecord(
        index=index,
        role=role,
        tool_results_added=len(after.tool_results) - len(before.tool_results),
        evidence_added=len(after.evidence) - len(before.evidence),
        runtime_steps_added=len(after.runtime_steps) - len(before.runtime_steps),
        answer_created=before.answer is None and after.answer is not None,
    )
