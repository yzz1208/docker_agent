from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from docker_agent.tools.docker_cli import DockerToolResult


class ToolErrorType(StrEnum):
    """Machine-readable error categories shared by future tool adapters."""

    NONE = "none"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    DAEMON_UNAVAILABLE = "daemon_unavailable"
    COMMAND_FAILED = "command_failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Adapter-neutral tool result used by the upgraded agent core."""

    tool_name: str
    ok: bool
    output: str
    error: str | None
    error_type: ToolErrorType
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = None

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool_name must not be empty")
        if self.ok and self.error_type is not ToolErrorType.NONE:
            raise ValueError("successful ToolResult must use error_type=none")
        if not self.ok and self.error_type is ToolErrorType.NONE:
            raise ValueError("failed ToolResult must have a non-none error_type")


def classify_docker_tool_error(result: DockerToolResult) -> ToolErrorType:
    """Map Docker CLI failures into stable core error categories."""

    if result.ok:
        return ToolErrorType.NONE

    text = f"{result.stdout}\n{result.stderr}".casefold()

    if "timed out" in text or "timeout" in text:
        return ToolErrorType.TIMEOUT

    if "permission denied" in text or "access is denied" in text:
        return ToolErrorType.PERMISSION_DENIED

    if (
        "no such container" in text
        or "no such object" in text
        or "container not found" in text
    ):
        return ToolErrorType.NOT_FOUND

    if (
        "cannot connect to the docker daemon" in text
        or "is the docker daemon running" in text
        or "docker daemon is not running" in text
        or "error during connect" in text
    ):
        return ToolErrorType.DAEMON_UNAVAILABLE

    if result.returncode != 0:
        return ToolErrorType.COMMAND_FAILED

    return ToolErrorType.UNKNOWN


def from_docker_tool_result(result: DockerToolResult) -> ToolResult:
    """Convert a Docker-specific result without changing existing Docker behavior."""

    error_type = classify_docker_tool_error(result)
    output = result.stdout.strip()
    error = None

    if not result.ok:
        error = result.stderr.strip() or result.output.strip() or "Docker command failed"

    return ToolResult(
        tool_name=result.tool,
        ok=result.ok,
        output=output,
        error=error,
        error_type=error_type,
        metadata={
            "adapter": "docker_cli",
            "command": result.command,
            "returncode": result.returncode,
        },
        raw=result,
    )
