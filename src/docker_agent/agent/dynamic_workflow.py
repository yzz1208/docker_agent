from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.dynamic_planner import (
    DynamicPlannerError,
    DynamicRuntimeDecision,
    plan_runtime_action,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext, build_runtime_evidence
from docker_agent.agent.router import AgentRouteDecision, DockerToolName
from docker_agent.rag.llm import ChatModel
from docker_agent.tools.docker_cli import (
    DockerReadOnlyTools,
    DockerToolResult,
    DockerToolTimeout,
)


class DynamicWorkflowError(RuntimeError):
    """Raised when a dynamic runtime workflow cannot safely complete."""


@dataclass(frozen=True, slots=True)
class DynamicRuntimeStep:
    step: int
    decision: DynamicRuntimeDecision
    result: DockerToolResult | None


@dataclass(frozen=True, slots=True)
class DynamicRuntimeResult:
    results: tuple[DockerToolResult, ...]
    evidence: RuntimeEvidenceContext
    trace: tuple[DynamicRuntimeStep, ...]


def run_dynamic_runtime_workflow(
    *,
    question: str,
    route: AgentRouteDecision,
    planner_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
) -> DynamicRuntimeResult:
    """Iteratively choose one read-only Docker tool, observe, and decide again."""

    if route.route != "runtime_tools":
        raise ValueError("dynamic runtime workflow requires runtime_tools route")
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")

    results: list[DockerToolResult] = []
    trace: list[DynamicRuntimeStep] = []
    used_tools: list[DockerToolName] = []

    for step in range(1, max_steps + 1):
        evidence = build_runtime_evidence(
            tuple(results),
            max_chars=evidence_max_chars,
        )
        decision = plan_runtime_action(
            question=question,
            container_ref=route.container_ref,
            used_tools=tuple(used_tools),
            evidence=evidence,
            model=planner_model,
        )

        if decision.action == "finish":
            if not results:
                raise DynamicWorkflowError(
                    "Planner finished before collecting any runtime evidence"
                )
            trace.append(
                DynamicRuntimeStep(step=step, decision=decision, result=None)
            )
            return DynamicRuntimeResult(
                results=tuple(results),
                evidence=evidence,
                trace=tuple(trace),
            )

        assert decision.tool is not None
        try:
            result = execute_runtime_tool(
                decision.tool,
                container_ref=route.container_ref,
                docker_tools=docker_tools,
            )
        except DockerToolTimeout as exc:
            result = runtime_timeout_result(
                decision.tool,
                container_ref=route.container_ref,
                message=str(exc),
            )
        except (ValueError, DynamicPlannerError) as exc:
            raise DynamicWorkflowError(str(exc)) from exc

        used_tools.append(decision.tool)
        results.append(result)
        trace.append(
            DynamicRuntimeStep(step=step, decision=decision, result=result)
        )

    final_evidence = build_runtime_evidence(
        tuple(results),
        max_chars=evidence_max_chars,
    )
    raise DynamicWorkflowError(
        f"Dynamic runtime workflow exceeded max_steps={max_steps} "
        f"after tools={used_tools}; last evidence chars={len(final_evidence.text)}"
    )


def execute_runtime_tool(
    tool: DockerToolName,
    *,
    container_ref: str | None,
    docker_tools: DockerReadOnlyTools,
) -> DockerToolResult:
    if tool == "docker_info":
        return docker_tools.info()
    if tool == "docker_ps":
        return docker_tools.ps()

    if container_ref is None:
        raise DynamicWorkflowError(f"{tool} requires container_ref")
    if tool == "docker_inspect":
        return docker_tools.inspect(container_ref)
    if tool == "docker_logs":
        return docker_tools.logs(container_ref)
    if tool == "docker_stats":
        return docker_tools.stats(container_ref)

    raise DynamicWorkflowError(f"Unsupported validated runtime tool: {tool}")



def runtime_timeout_result(
    tool: DockerToolName,
    *,
    container_ref: str | None,
    message: str,
) -> DockerToolResult:
    """Convert a tool timeout into bounded runtime evidence for the planner."""

    if tool == "docker_info":
        command = ("docker", "info")
    elif tool == "docker_ps":
        command = ("docker", "ps", "--all")
    elif tool == "docker_inspect" and container_ref is not None:
        command = ("docker", "inspect", container_ref)
    elif tool == "docker_logs" and container_ref is not None:
        command = ("docker", "logs", "--tail", "100", container_ref)
    elif tool == "docker_stats" and container_ref is not None:
        command = ("docker", "stats", "--no-stream", container_ref)
    else:
        command = ("docker", tool)

    return DockerToolResult(
        tool=tool,
        command=command,
        returncode=124,
        stdout="",
        stderr=message,
    )
