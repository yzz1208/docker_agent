"""Core domain models shared across agent runtimes and adapters."""

from docker_agent.core.tool_result import (
    ToolErrorType,
    ToolResult,
    classify_docker_tool_error,
    from_docker_tool_result,
)

__all__ = [
    "ToolErrorType",
    "ToolResult",
    "classify_docker_tool_error",
    "from_docker_tool_result",
]
