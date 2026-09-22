from docker_agent.agent.evidence import build_runtime_evidence
from docker_agent.tools.docker_cli import DockerToolResult


def _result(tool: str, output: str, *, returncode: int = 0) -> DockerToolResult:
    return DockerToolResult(
        tool=tool,
        command=("docker", tool),
        returncode=returncode,
        stdout=output,
        stderr="",
    )


def test_build_runtime_evidence_assigns_runtime_labels() -> None:
    context = build_runtime_evidence(
        (
            _result("docker_stats", '{"MemUsage":"64MiB"}'),
            _result("docker_logs", "error line"),
        ),
        max_chars=2_000,
    )

    assert "[R1]" in context.text
    assert "[R2]" in context.text
    assert context.sources[0].tool == "docker_stats"
    assert context.sources[1].index == 2
    assert context.truncated is False


def test_build_runtime_evidence_marks_tool_error() -> None:
    context = build_runtime_evidence(
        (_result("docker_logs", "container not found", returncode=1),),
        max_chars=2_000,
    )

    assert "error(returncode=1)" in context.text
    assert context.sources[0].ok is False


def test_build_runtime_evidence_truncates_to_budget() -> None:
    context = build_runtime_evidence(
        (_result("docker_inspect", "x" * 5_000),),
        max_chars=300,
    )

    assert len(context.text) <= 300
    assert context.truncated is True


def test_build_runtime_evidence_marks_timeout_without_return_code() -> None:
    result = DockerToolResult(
        tool="docker_stats",
        command=("docker", "stats", "--no-stream", "web"),
        returncode=124,
        stdout="",
        stderr="docker_stats timed out after 15 seconds",
    )

    context = build_runtime_evidence((result,), max_chars=2_000)

    assert "Status: timeout" in context.text
    assert "returncode=124" not in context.text
    assert "timed out after 15 seconds" in context.text
