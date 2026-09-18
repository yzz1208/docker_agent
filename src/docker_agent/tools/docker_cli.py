from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

_CONTAINER_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

CommandRunner = Callable[
    [Sequence[str], float],
    subprocess.CompletedProcess[str],
]


class DockerToolTimeout(RuntimeError):
    """Raised when a Docker diagnostic command exceeds its timeout."""


@dataclass(frozen=True, slots=True)
class DockerToolResult:
    """Structured result returned by a read-only Docker diagnostic tool."""

    tool: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        stdout = self.stdout.strip()
        stderr = self.stderr.strip()
        if stdout and stderr:
            return f"{stdout}\n{stderr}"
        return stdout or stderr


def _default_runner(
    args: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )


def validate_container_ref(container: str) -> str:
    """Validate a Docker container name/ID before placing it in argv."""

    value = container.strip()
    if not value:
        raise ValueError("container must not be empty")
    if not _CONTAINER_REF_RE.fullmatch(value):
        raise ValueError(
            "container must be a Docker name/ID containing only letters, digits, "
            "underscore, dot, or hyphen"
        )
    return value


class DockerReadOnlyTools:
    """Small allowlisted wrapper around local Docker CLI diagnostics.

    The wrapper intentionally exposes only read-only commands. User text is never
    interpreted as a shell command and is never appended as arbitrary CLI flags.
    """

    def __init__(
        self,
        *,
        executable: str = "docker",
        timeout_seconds: float = 15.0,
        max_log_lines: int = 200,
        runner: CommandRunner | None = None,
    ) -> None:
        if not executable.strip():
            raise ValueError("executable must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_log_lines <= 0:
            raise ValueError("max_log_lines must be positive")

        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.max_log_lines = max_log_lines
        self._runner = runner or _default_runner

    def info(self) -> DockerToolResult:
        """Return Docker daemon/system information."""

        return self._run("docker_info", ["info"])

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        """List containers as JSON lines."""

        args = ["ps"]
        if include_stopped:
            args.append("--all")
        args.extend(["--no-trunc", "--format", "{{json .}}"])
        return self._run("docker_ps", args)

    def inspect(self, container: str) -> DockerToolResult:
        """Inspect one container and return a compact non-secret diagnostic summary."""

        container = validate_container_ref(container)
        result = self._run("docker_inspect", ["inspect", container])
        if not result.ok:
            return result

        summary = _summarize_inspect_output(result.stdout)
        if summary is None:
            return result

        return DockerToolResult(
            tool=result.tool,
            command=result.command,
            returncode=result.returncode,
            stdout=json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
            stderr=result.stderr,
        )

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        """Return a bounded number of recent container log lines."""

        container = validate_container_ref(container)
        if tail <= 0:
            raise ValueError("tail must be positive")
        if tail > self.max_log_lines:
            raise ValueError(
                f"tail must be less than or equal to {self.max_log_lines}"
            )
        return self._run(
            "docker_logs",
            ["logs", "--tail", str(tail), container],
        )

    def stats(self, container: str) -> DockerToolResult:
        """Return one no-stream resource usage snapshot as JSON."""

        container = validate_container_ref(container)
        return self._run(
            "docker_stats",
            ["stats", "--no-stream", "--format", "{{json .}}", container],
        )

    def _run(self, tool: str, args: list[str]) -> DockerToolResult:
        command = (self.executable, *args)
        try:
            completed = self._runner(command, self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise DockerToolTimeout(
                f"{tool} timed out after {self.timeout_seconds:g} seconds"
            ) from exc

        return DockerToolResult(
            tool=tool,
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def _summarize_inspect_output(raw: str) -> dict[str, Any] | None:
    """Reduce docker inspect JSON to fields useful for diagnosis.

    Environment values are deliberately excluded. Only environment variable names
    are retained so runtime evidence does not send passwords/tokens to the model.
    """

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None

    item = payload[0]
    state = item.get("State") if isinstance(item.get("State"), dict) else {}
    config = item.get("Config") if isinstance(item.get("Config"), dict) else {}
    host_config = (
        item.get("HostConfig") if isinstance(item.get("HostConfig"), dict) else {}
    )
    restart_policy = (
        host_config.get("RestartPolicy")
        if isinstance(host_config.get("RestartPolicy"), dict)
        else {}
    )

    env = config.get("Env")
    env_keys: list[str] = []
    if isinstance(env, list):
        for entry in env:
            if not isinstance(entry, str):
                continue
            key = entry.split("=", 1)[0].strip()
            if key and key not in env_keys:
                env_keys.append(key)

    return {
        "Id": item.get("Id"),
        "Name": item.get("Name"),
        "Image": config.get("Image"),
        "Entrypoint": config.get("Entrypoint"),
        "Cmd": config.get("Cmd"),
        "EnvKeys": env_keys,
        "RestartCount": item.get("RestartCount"),
        "RestartPolicy": {
            "Name": restart_policy.get("Name"),
            "MaximumRetryCount": restart_policy.get("MaximumRetryCount"),
        },
        "State": {
            "Status": state.get("Status"),
            "Running": state.get("Running"),
            "Restarting": state.get("Restarting"),
            "OOMKilled": state.get("OOMKilled"),
            "Dead": state.get("Dead"),
            "ExitCode": state.get("ExitCode"),
            "Error": state.get("Error"),
            "StartedAt": state.get("StartedAt"),
            "FinishedAt": state.get("FinishedAt"),
        },
    }
