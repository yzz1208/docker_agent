from docker_agent.agent.dynamic_workflow import run_dynamic_runtime_workflow
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.tools.docker_cli import DockerToolResult, DockerToolTimeout


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        return self.responses.pop(0)


class FakeDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect(self, container: str) -> DockerToolResult:
        self.calls.append("docker_inspect")
        return DockerToolResult(
            tool="docker_inspect",
            command=("docker", "inspect", container),
            returncode=0,
            stdout='{"State":{"OOMKilled":true,"ExitCode":137}}',
            stderr="",
        )

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        self.calls.append("docker_logs")
        return DockerToolResult(
            tool="docker_logs",
            command=("docker", "logs", "--tail", str(tail), container),
            returncode=0,
            stdout="database connection refused",
            stderr="",
        )

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append("docker_stats")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", container),
            returncode=0,
            stdout='{"MemUsage":"128MiB / 2GiB"}',
            stderr="",
        )

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected docker_info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        raise AssertionError("unexpected docker_ps")


def _route(container_ref: str = "web") -> AgentRouteDecision:
    return AgentRouteDecision(
        route="runtime_tools",
        reason="runtime needed",
        container_ref=container_ref,
        tools=("docker_inspect", "docker_logs"),
        clarification=None,
        use_docs=False,
    )


def test_dynamic_oom_flow_stops_after_inspect() -> None:
    model = SequenceModel(
        [
            '{"action":"tool","tool":"docker_inspect","reason":"check OOM state"}',
            '{"action":"finish","tool":null,"reason":"OOMKilled is sufficient"}',
        ]
    )
    tools = FakeDockerTools()

    result = run_dynamic_runtime_workflow(
        question="web 是不是被 OOM 杀了？",
        route=_route(),
        planner_model=model,
        docker_tools=tools,  # type: ignore[arg-type]
    )

    assert tools.calls == ["docker_inspect"]
    assert [step.decision.action for step in result.trace] == ["tool", "finish"]
    assert "[R1]" in result.evidence.text


def test_dynamic_crash_flow_observes_inspect_before_logs() -> None:
    model = SequenceModel(
        [
            '{"action":"tool","tool":"docker_inspect","reason":"check state"}',
            '{"action":"tool","tool":"docker_logs","reason":"state lacks root cause"}',
            '{"action":"finish","tool":null,"reason":"logs explain failure"}',
        ]
    )
    tools = FakeDockerTools()

    result = run_dynamic_runtime_workflow(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=model,
        docker_tools=tools,  # type: ignore[arg-type]
    )

    assert tools.calls == ["docker_inspect", "docker_logs"]
    assert "[R1]" in model.prompts[1]
    assert len(result.results) == 2



class FailureDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect(self, container: str) -> DockerToolResult:
        self.calls.append("docker_inspect")
        return DockerToolResult(
            tool="docker_inspect",
            command=("docker", "inspect", container),
            returncode=1,
            stdout="",
            stderr=f"Error: No such object: {container}",
        )

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        self.calls.append("docker_ps")
        return DockerToolResult(
            tool="docker_ps",
            command=("docker", "ps", "--all"),
            returncode=0,
            stdout='{"Names":"web-old","State":"exited"}',
            stderr="",
        )

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        raise AssertionError("unexpected docker_logs")

    def stats(self, container: str) -> DockerToolResult:
        raise AssertionError("unexpected docker_stats")

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected docker_info")


def test_dynamic_failure_flow_can_verify_missing_container_with_ps() -> None:
    model = SequenceModel(
        [
            '{"action":"tool","tool":"docker_inspect","reason":"inspect named container"}',
            '{"action":"tool","tool":"docker_ps","reason":"verify available names"}',
            '{"action":"finish","tool":null,"reason":"named container is absent"}',
        ]
    )
    tools = FailureDockerTools()

    result = run_dynamic_runtime_workflow(
        question="web 为什么退出了？",
        route=_route("web"),
        planner_model=model,
        docker_tools=tools,  # type: ignore[arg-type]
    )

    assert tools.calls == ["docker_inspect", "docker_ps"]
    assert result.results[0].ok is False
    assert result.results[1].ok is True
    assert "[R1]" in model.prompts[1]
    assert "[R2]" in model.prompts[2]



class TimeoutDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append("docker_stats")
        raise DockerToolTimeout("docker_stats timed out after 15 seconds")

    def inspect(self, container: str) -> DockerToolResult:
        raise AssertionError("unexpected docker_inspect")

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        raise AssertionError("unexpected docker_logs")

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected docker_info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        raise AssertionError("unexpected docker_ps")


def test_dynamic_timeout_becomes_runtime_evidence_instead_of_crashing() -> None:
    model = SequenceModel(
        [
            '{"action":"tool","tool":"docker_stats","reason":"measure memory"}',
            '{"action":"finish","tool":null,"reason":"stats timed out; report limitation"}',
        ]
    )
    tools = TimeoutDockerTools()

    result = run_dynamic_runtime_workflow(
        question="web 现在用了多少内存？",
        route=_route("web"),
        planner_model=model,
        docker_tools=tools,  # type: ignore[arg-type]
    )

    assert tools.calls == ["docker_stats"]
    assert result.results[0].ok is False
    assert result.results[0].returncode == 124
    assert "timed out after 15 seconds" in result.evidence.text
    assert "[R1]" in model.prompts[1]
