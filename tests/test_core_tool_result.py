import pytest

from docker_agent.core.tool_result import (
    ToolErrorType,
    ToolResult,
    classify_docker_tool_error,
    from_docker_tool_result,
)
from docker_agent.tools.docker_cli import DockerToolResult


def _docker_result(
    *,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    tool: str = "docker_info",
) -> DockerToolResult:
    return DockerToolResult(
        tool=tool,
        command=("docker", "info"),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_successful_docker_result_maps_to_none_error() -> None:
    result = _docker_result(returncode=0, stdout="Server Version: 29.8.0")

    converted = from_docker_tool_result(result)

    assert converted.ok is True
    assert converted.output == "Server Version: 29.8.0"
    assert converted.error is None
    assert converted.error_type is ToolErrorType.NONE
    assert converted.metadata["adapter"] == "docker_cli"
    assert converted.metadata["returncode"] == 0
    assert converted.raw is result


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "docker_stats timed out after 15 seconds",
            ToolErrorType.TIMEOUT,
        ),
        (
            "Error: No such object: web-prod",
            ToolErrorType.NOT_FOUND,
        ),
        (
            "permission denied while trying to connect to the Docker daemon socket",
            ToolErrorType.PERMISSION_DENIED,
        ),
        (
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
            ToolErrorType.DAEMON_UNAVAILABLE,
        ),
        (
            "configured logging driver does not support reading",
            ToolErrorType.COMMAND_FAILED,
        ),
    ],
)
def test_classify_docker_tool_error(stderr: str, expected: ToolErrorType) -> None:
    result = _docker_result(returncode=1, stderr=stderr)

    assert classify_docker_tool_error(result) is expected


def test_permission_denied_wins_over_generic_daemon_wording() -> None:
    result = _docker_result(
        returncode=1,
        stderr=(
            "permission denied while trying to connect to the Docker daemon "
            "socket at unix:///var/run/docker.sock"
        ),
    )

    assert classify_docker_tool_error(result) is ToolErrorType.PERMISSION_DENIED


def test_failed_conversion_separates_stdout_from_error() -> None:
    result = _docker_result(
        returncode=1,
        stdout="partial output",
        stderr="command failed",
        tool="docker_logs",
    )

    converted = from_docker_tool_result(result)

    assert converted.ok is False
    assert converted.output == "partial output"
    assert converted.error == "command failed"
    assert converted.error_type is ToolErrorType.COMMAND_FAILED
    assert converted.tool_name == "docker_logs"


def test_tool_result_rejects_inconsistent_success_error_state() -> None:
    with pytest.raises(ValueError, match="successful ToolResult"):
        ToolResult(
            tool_name="docker_info",
            ok=True,
            output="ok",
            error=None,
            error_type=ToolErrorType.COMMAND_FAILED,
        )


def test_tool_result_rejects_failed_none_error_type() -> None:
    with pytest.raises(ValueError, match="failed ToolResult"):
        ToolResult(
            tool_name="docker_info",
            ok=False,
            output="",
            error="failed",
            error_type=ToolErrorType.NONE,
        )


def test_classifier_reads_stderr_even_when_stdout_is_present() -> None:
    result = _docker_result(
        returncode=1,
        stdout="partial diagnostic output",
        stderr="permission denied while trying to connect to the Docker daemon socket",
    )

    assert classify_docker_tool_error(result) is ToolErrorType.PERMISSION_DENIED
