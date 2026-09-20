import pytest

from docker_agent.agent.dynamic_workflow import (
    DynamicWorkflowError,
    run_dynamic_runtime_workflow,
)
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.graph.runtime_loop import run_runtime_loop_graph
from docker_agent.tools.docker_cli import DockerToolResult, DockerToolTimeout


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return self.responses.pop(0)


class FakeDockerTools:
    def __init__(self, *, timeout_stats: bool = False) -> None:
        self.calls: list[str] = []
        self.timeout_stats = timeout_stats

    def inspect(self, container: str) -> DockerToolResult:
        self.calls.append("docker_inspect")
        return DockerToolResult(
            tool="docker_inspect",
            command=("docker", "inspect", container),
            returncode=0,
            stdout='{"State":{"OOMKilled":false,"ExitCode":1}}',
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
        if self.timeout_stats:
            raise DockerToolTimeout("docker_stats timed out after 15 seconds")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", "--no-stream", container),
            returncode=0,
            stdout='{"MemUsage":"128MiB / 2GiB"}',
            stderr="",
        )

    def info(self) -> DockerToolResult:
        self.calls.append("docker_info")
        return DockerToolResult(
            tool="docker_info",
            command=("docker", "info"),
            returncode=0,
            stdout="Server Version: 29.8.0",
            stderr="",
        )

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        self.calls.append("docker_ps")
        return DockerToolResult(
            tool="docker_ps",
            command=("docker", "ps", "--all"),
            returncode=0,
            stdout='{"Names":"web","State":"running"}',
            stderr="",
        )


def _route(container_ref: str | None = "web") -> AgentRouteDecision:
    return AgentRouteDecision(
        route="runtime_tools",
        reason="runtime needed",
        container_ref=container_ref,
        tools=("docker_inspect",),
        clarification=None,
        use_docs=False,
    )


def _signature(result) -> tuple[object, ...]:
    return (
        tuple(
            (
                item.tool,
                item.command,
                item.returncode,
                item.stdout,
                item.stderr,
            )
            for item in result.results
        ),
        tuple(
            (
                step.step,
                step.decision.action,
                step.decision.tool,
                step.decision.reason,
                step.result.returncode if step.result is not None else None,
            )
            for step in result.trace
        ),
        result.evidence.text,
        result.evidence.truncated,
    )


def test_runtime_loop_graph_matches_legacy_multi_step_diagnosis() -> None:
    responses = [
        '{"action":"tool","tool":"docker_inspect","reason":"check state"}',
        '{"action":"tool","tool":"docker_logs","reason":"find root cause"}',
        '{"action":"finish","tool":null,"reason":"logs explain failure"}',
    ]
    legacy_tools = FakeDockerTools()
    graph_tools = FakeDockerTools()

    legacy = run_dynamic_runtime_workflow(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=legacy_tools,  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=graph_tools,  # type: ignore[arg-type]
    )

    assert legacy_tools.calls == graph_tools.calls == [
        "docker_inspect",
        "docker_logs",
    ]
    assert _signature(graph) == _signature(legacy)


def test_runtime_loop_graph_matches_legacy_timeout_evidence() -> None:
    responses = [
        '{"action":"tool","tool":"docker_stats","reason":"measure memory"}',
        '{"action":"finish","tool":null,"reason":"report timeout"}',
    ]
    legacy_tools = FakeDockerTools(timeout_stats=True)
    graph_tools = FakeDockerTools(timeout_stats=True)

    legacy = run_dynamic_runtime_workflow(
        question="web 现在用了多少内存？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=legacy_tools,  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web 现在用了多少内存？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=graph_tools,  # type: ignore[arg-type]
    )

    assert _signature(graph) == _signature(legacy)
    assert graph.results[0].returncode == 124
    assert "timed out after 15 seconds" in graph.evidence.text


def test_runtime_loop_graph_matches_legacy_direct_stats_flow() -> None:
    responses = [
        '{"action":"tool","tool":"docker_stats","reason":"measure memory"}',
        '{"action":"finish","tool":null,"reason":"measurement is enough"}',
    ]

    legacy = run_dynamic_runtime_workflow(
        question="web 现在用了多少内存？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web 现在用了多少内存？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
    )

    assert _signature(graph) == _signature(legacy)



def test_runtime_loop_graph_matches_finish_before_evidence_guard() -> None:
    response = ['{"action":"finish","tool":null,"reason":"done"}']

    with pytest.raises(
        DynamicWorkflowError,
        match="finished before collecting any runtime evidence",
    ):
        run_dynamic_runtime_workflow(
            question="web 为什么退出了？",
            route=_route(),
            planner_model=SequenceModel(list(response)),
            docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        DynamicWorkflowError,
        match="finished before collecting any runtime evidence",
    ):
        run_runtime_loop_graph(
            question="web 为什么退出了？",
            route=_route(),
            planner_model=SequenceModel(list(response)),
            docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
        )


def test_runtime_loop_graph_matches_max_step_exhaustion() -> None:
    response = [
        '{"action":"tool","tool":"docker_inspect","reason":"check state"}',
    ]

    with pytest.raises(
        DynamicWorkflowError,
        match="exceeded max_steps=1",
    ):
        run_dynamic_runtime_workflow(
            question="web 为什么退出了？",
            route=_route(),
            planner_model=SequenceModel(list(response)),
            docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
            max_steps=1,
        )

    with pytest.raises(
        DynamicWorkflowError,
        match="exceeded max_steps=1",
    ):
        run_runtime_loop_graph(
            question="web 为什么退出了？",
            route=_route(),
            planner_model=SequenceModel(list(response)),
            docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
            max_steps=1,
        )



class FailureScenarioDockerTools:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.calls: list[str] = []

    def inspect(self, container: str) -> DockerToolResult:
        self.calls.append("docker_inspect")
        if self.scenario == "not_found":
            return DockerToolResult(
                tool="docker_inspect",
                command=("docker", "inspect", container),
                returncode=1,
                stdout="",
                stderr=f"Error: No such object: {container}",
            )
        if self.scenario == "permission":
            return DockerToolResult(
                tool="docker_inspect",
                command=("docker", "inspect", container),
                returncode=1,
                stdout="",
                stderr=(
                    "permission denied while trying to connect to the "
                    "Docker daemon socket"
                ),
            )
        return DockerToolResult(
            tool="docker_inspect",
            command=("docker", "inspect", container),
            returncode=0,
            stdout='{"State":{"Status":"exited","ExitCode":1}}',
            stderr="",
        )

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        self.calls.append("docker_logs")
        return DockerToolResult(
            tool="docker_logs",
            command=("docker", "logs", "--tail", str(tail), container),
            returncode=1,
            stdout="",
            stderr=(
                "Error response from daemon: configured logging driver "
                "does not support reading"
            ),
        )

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append("docker_stats")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", "--no-stream", container),
            returncode=1,
            stdout="",
            stderr=f"Error response from daemon: container {container} is not running",
        )

    def info(self) -> DockerToolResult:
        self.calls.append("docker_info")
        return DockerToolResult(
            tool="docker_info",
            command=("docker", "info"),
            returncode=1,
            stdout="",
            stderr=(
                "permission denied while trying to connect to the "
                "Docker daemon socket"
            ),
        )

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        self.calls.append("docker_ps")
        return DockerToolResult(
            tool="docker_ps",
            command=("docker", "ps", "--all"),
            returncode=0,
            stdout=(
                '{"Names":"web-prod-old","State":"exited"}\n'
                '{"Names":"web-1","State":"running"}'
            ),
            stderr="",
        )


def test_runtime_loop_graph_matches_container_not_found_recovery() -> None:
    responses = [
        '{"action":"tool","tool":"docker_inspect","reason":"inspect target"}',
        '{"action":"tool","tool":"docker_ps","reason":"list candidates"}',
        '{"action":"finish","tool":null,"reason":"target not found"}',
    ]
    legacy_tools = FailureScenarioDockerTools("not_found")
    graph_tools = FailureScenarioDockerTools("not_found")

    legacy = run_dynamic_runtime_workflow(
        question="web-prod 为什么退出了？",
        route=_route("web-prod"),
        planner_model=SequenceModel(list(responses)),
        docker_tools=legacy_tools,  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web-prod 为什么退出了？",
        route=_route("web-prod"),
        planner_model=SequenceModel(list(responses)),
        docker_tools=graph_tools,  # type: ignore[arg-type]
    )

    assert legacy_tools.calls == graph_tools.calls == [
        "docker_inspect",
        "docker_ps",
    ]
    assert _signature(graph) == _signature(legacy)


def test_runtime_loop_graph_matches_unavailable_logs_failure() -> None:
    responses = [
        '{"action":"tool","tool":"docker_inspect","reason":"inspect state"}',
        '{"action":"tool","tool":"docker_logs","reason":"read failure logs"}',
        '{"action":"finish","tool":null,"reason":"logs unavailable"}',
    ]
    legacy_tools = FailureScenarioDockerTools("logs_unavailable")
    graph_tools = FailureScenarioDockerTools("logs_unavailable")

    legacy = run_dynamic_runtime_workflow(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=legacy_tools,  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=graph_tools,  # type: ignore[arg-type]
    )

    assert legacy_tools.calls == graph_tools.calls == [
        "docker_inspect",
        "docker_logs",
    ]
    assert _signature(graph) == _signature(legacy)


def test_runtime_loop_graph_matches_permission_denied_failure() -> None:
    responses = [
        '{"action":"tool","tool":"docker_inspect","reason":"inspect target"}',
        '{"action":"finish","tool":null,"reason":"permission denied"}',
    ]
    legacy_tools = FailureScenarioDockerTools("permission")
    graph_tools = FailureScenarioDockerTools("permission")

    legacy = run_dynamic_runtime_workflow(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=legacy_tools,  # type: ignore[arg-type]
    )
    graph = run_runtime_loop_graph(
        question="web 为什么退出了？",
        route=_route(),
        planner_model=SequenceModel(list(responses)),
        docker_tools=graph_tools,  # type: ignore[arg-type]
    )

    assert legacy_tools.calls == graph_tools.calls == ["docker_inspect"]
    assert _signature(graph) == _signature(legacy)
