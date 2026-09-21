import subprocess

import pytest

from docker_agent.config import Settings
from docker_agent.tools.docker_cli import (
    DockerReadOnlyTools,
    build_docker_tools,
    validate_container_ref,
)


class RecordingRunner:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "ok",
        stderr: str = "",
    ) -> None:
        self.calls: list[tuple[tuple[str, ...], float]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(
        self,
        args: tuple[str, ...],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((tuple(args), timeout_seconds))
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def test_ps_builds_allowlisted_command_without_shell_text() -> None:
    runner = RecordingRunner(stdout='{"Names":"web"}')
    tools = DockerReadOnlyTools(runner=runner)

    result = tools.ps()

    assert result.ok is True
    assert result.tool == "docker_ps"
    assert runner.calls == [
        (
            (
                "docker",
                "ps",
                "--all",
                "--no-trunc",
                "--format",
                "{{json .}}",
            ),
            15.0,
        )
    ]


def test_inspect_accepts_normal_container_name() -> None:
    runner = RecordingRunner(stdout="[]")
    tools = DockerReadOnlyTools(runner=runner)

    tools.inspect("web-1")

    assert runner.calls[0][0] == ("docker", "inspect", "web-1")


@pytest.mark.parametrize(
    "container",
    ["", "--help", "web;rm", "web $(whoami)", "web/name"],
)
def test_container_ref_rejects_shell_or_flag_like_input(container: str) -> None:
    with pytest.raises(ValueError):
        validate_container_ref(container)


def test_logs_enforces_bounded_tail() -> None:
    tools = DockerReadOnlyTools(max_log_lines=200, runner=RecordingRunner())

    with pytest.raises(ValueError, match="less than or equal"):
        tools.logs("web", tail=201)


def test_logs_builds_exact_argv() -> None:
    runner = RecordingRunner(stdout="line")
    tools = DockerReadOnlyTools(runner=runner)

    tools.logs("web", tail=50)

    assert runner.calls[0][0] == (
        "docker",
        "logs",
        "--tail",
        "50",
        "web",
    )


def test_nonzero_docker_exit_is_returned_as_structured_result() -> None:
    runner = RecordingRunner(returncode=1, stdout="", stderr="daemon unavailable")
    tools = DockerReadOnlyTools(runner=runner)

    result = tools.info()

    assert result.ok is False
    assert result.output == "daemon unavailable"


def test_stats_uses_no_stream_mode() -> None:
    runner = RecordingRunner(stdout='{"CPUPerc":"1.2%"}')
    tools = DockerReadOnlyTools(runner=runner)

    tools.stats("api")

    assert runner.calls[0][0] == (
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        "api",
    )


def test_inspect_compacts_output_and_keeps_only_env_keys() -> None:
    runner = RecordingRunner(
        stdout=(
            '[{"Id":"abc","Name":"/web","RestartCount":2,'
            '"State":{"Status":"exited","ExitCode":1,"OOMKilled":false,'
            '"Running":false,"Restarting":false,"Dead":false,'
            '"Error":"","StartedAt":"start","FinishedAt":"finish"},'
            '"Config":{"Image":"postgres:16","Cmd":["postgres"],'
            '"Entrypoint":["docker-entrypoint.sh"],'
            '"Env":["POSTGRES_PASSWORD=super-secret","PATH=/usr/bin"]},'
            '"HostConfig":{"RestartPolicy":{"Name":"no","MaximumRetryCount":0}}}]'
        )
    )
    tools = DockerReadOnlyTools(runner=runner)

    result = tools.inspect("web")

    assert "super-secret" not in result.output
    assert '"EnvKeys":["POSTGRES_PASSWORD","PATH"]' in result.output
    assert '"ExitCode":1' in result.output
    assert '"RestartCount":2' in result.output


def test_mock_tool_mode_returns_deterministic_results_without_local_docker() -> None:
    settings = Settings(
        tool_mode="mock",
        docker_tool_timeout_seconds=3,
        docker_logs_max_lines=25,
    )

    tools = build_docker_tools(settings)

    info = tools.info()
    inspected = tools.inspect("demo")
    logs = tools.logs("demo", tail=10)
    stats = tools.stats("demo")

    assert info.ok is True
    assert '"ServerVersion":"mock"' in info.output
    assert '"Name":"/demo"' in inspected.output
    assert "mock container log line" in logs.output
    assert '"CPUPerc":"0.10%"' in stats.output


def test_local_tool_mode_keeps_real_cli_runner(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        args: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(args))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="local-ok",
            stderr="",
        )

    monkeypatch.setattr(
        "docker_agent.tools.docker_cli.subprocess.run",
        fake_run,
    )
    settings = Settings(tool_mode="local")

    tools = build_docker_tools(settings)
    result = tools.info()

    assert result.output == "local-ok"
    assert calls == [("docker", "info")]
