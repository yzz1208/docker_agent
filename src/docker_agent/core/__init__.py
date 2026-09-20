"""Core domain models shared across agent runtimes and adapters."""

from docker_agent.core.evidence import (
    Evidence,
    EvidenceBundle,
    EvidenceKind,
    citation_source_to_evidence,
    make_evidence_id,
    runtime_tool_result_to_evidence,
    user_message_to_evidence,
)
from docker_agent.core.state import AgentState, AgentStep
from docker_agent.core.tool_result import (
    ToolErrorType,
    ToolResult,
    classify_docker_tool_error,
    from_docker_tool_result,
)

__all__ = [
    "AgentState",
    "AgentStep",
    "Evidence",
    "EvidenceBundle",
    "EvidenceKind",
    "ToolErrorType",
    "ToolResult",
    "citation_source_to_evidence",
    "classify_docker_tool_error",
    "from_docker_tool_result",
    "make_evidence_id",
    "runtime_tool_result_to_evidence",
    "user_message_to_evidence",
]
