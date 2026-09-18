from __future__ import annotations

from docker_agent.agent.router import AgentRouteDecision
from docker_agent.tools.docker_cli import DockerReadOnlyTools, DockerToolResult


def execute_runtime_plan(
    decision: AgentRouteDecision,
    tools: DockerReadOnlyTools,
) -> tuple[DockerToolResult, ...]:
    """Execute only allowlisted tools from a validated runtime route."""

    if decision.route != "runtime_tools":
        raise ValueError("execute_runtime_plan requires a runtime_tools decision")

    results: list[DockerToolResult] = []
    for tool_name in decision.tools:
        if tool_name == "docker_info":
            results.append(tools.info())
        elif tool_name == "docker_ps":
            results.append(tools.ps())
        elif tool_name == "docker_inspect":
            assert decision.container_ref is not None
            results.append(tools.inspect(decision.container_ref))
        elif tool_name == "docker_logs":
            assert decision.container_ref is not None
            results.append(tools.logs(decision.container_ref))
        elif tool_name == "docker_stats":
            assert decision.container_ref is not None
            results.append(tools.stats(decision.container_ref))
        else:
            raise ValueError(f"Unsupported validated tool: {tool_name}")

    return tuple(results)
