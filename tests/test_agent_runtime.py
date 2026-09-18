from docker_agent.agent.router import AgentRouteDecision
from docker_agent.agent.runtime import execute_runtime_plan
from docker_agent.tools.docker_cli import DockerToolResult


class FakeDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _result(self, tool: str) -> DockerToolResult:
        self.calls.append(tool)
        return DockerToolResult(
            tool=tool,
            command=("docker", tool),
            returncode=0,
            stdout=tool,
            stderr="",
        )

    def info(self) -> DockerToolResult:
        return self._result("docker_info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        assert include_stopped is True
        return self._result("docker_ps")

    def inspect(self, container: str) -> DockerToolResult:
        assert container == "web"
        return self._result("docker_inspect")

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        assert container == "web"
        assert tail == 100
        return self._result("docker_logs")

    def stats(self, container: str) -> DockerToolResult:
        assert container == "web"
        return self._result("docker_stats")


def test_execute_runtime_plan_runs_tools_in_validated_order() -> None:
    decision = AgentRouteDecision(
        route="runtime_tools",
        reason="diagnose restart",
        container_ref="web",
        tools=("docker_inspect", "docker_logs"),
        clarification=None,
    )
    tools = FakeDockerTools()

    results = execute_runtime_plan(decision, tools)  # type: ignore[arg-type]

    assert tools.calls == ["docker_inspect", "docker_logs"]
    assert [result.tool for result in results] == ["docker_inspect", "docker_logs"]
