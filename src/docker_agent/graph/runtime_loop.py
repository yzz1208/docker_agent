from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from docker_agent.agent.dynamic_planner import (
    DynamicPlannerError,
    DynamicRuntimeDecision,
    plan_runtime_action,
)
from docker_agent.agent.dynamic_workflow import (
    DynamicRuntimeResult,
    DynamicRuntimeStep,
    DynamicWorkflowError,
    execute_runtime_tool,
    runtime_timeout_result,
)
from docker_agent.agent.evidence import RuntimeEvidenceContext, build_runtime_evidence
from docker_agent.agent.router import AgentRouteDecision, DockerToolName
from docker_agent.rag.llm import ChatModel
from docker_agent.tools.docker_cli import (
    DockerReadOnlyTools,
    DockerToolResult,
    DockerToolTimeout,
)

RuntimeLoopEdge = Literal["tool", "finish"]
AfterToolEdge = Literal["plan", "exhausted"]


class RuntimeLoopState(TypedDict):
    """Transport state for the Phase 2B runtime planner/tool loop."""

    question: str
    route: AgentRouteDecision
    results: tuple[DockerToolResult, ...]
    evidence: RuntimeEvidenceContext
    trace: tuple[DynamicRuntimeStep, ...]
    used_tools: tuple[DockerToolName, ...]
    decision: DynamicRuntimeDecision | None
    step: int
    finished: bool


def build_runtime_loop_graph(
    *,
    planner_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
):
    """Compile the node-level runtime loop without changing planner semantics."""

    if max_steps <= 0:
        raise ValueError("max_steps must be positive")

    def plan_node(state: RuntimeLoopState) -> dict[str, object]:
        evidence = build_runtime_evidence(
            state["results"],
            max_chars=evidence_max_chars,
        )
        decision = plan_runtime_action(
            question=state["question"],
            container_ref=state["route"].container_ref,
            used_tools=state["used_tools"],
            evidence=evidence,
            model=planner_model,
        )
        if decision.action == "finish" and not state["results"]:
            raise DynamicWorkflowError(
                "Planner finished before collecting any runtime evidence"
            )
        return {
            "evidence": evidence,
            "decision": decision,
        }

    def after_plan(state: RuntimeLoopState) -> RuntimeLoopEdge:
        decision = state["decision"]
        if decision is None:
            raise DynamicWorkflowError("runtime planner decision is missing")
        return "finish" if decision.action == "finish" else "tool"

    def tool_node(state: RuntimeLoopState) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action != "tool" or decision.tool is None:
            raise DynamicWorkflowError("tool node requires a validated tool decision")

        try:
            result = execute_runtime_tool(
                decision.tool,
                container_ref=state["route"].container_ref,
                docker_tools=docker_tools,
            )
        except DockerToolTimeout as exc:
            result = runtime_timeout_result(
                decision.tool,
                container_ref=state["route"].container_ref,
                message=str(exc),
            )
        except (ValueError, DynamicPlannerError) as exc:
            raise DynamicWorkflowError(str(exc)) from exc

        runtime_step = DynamicRuntimeStep(
            step=state["step"],
            decision=decision,
            result=result,
        )
        return {
            "results": (*state["results"], result),
            "trace": (*state["trace"], runtime_step),
            "used_tools": (*state["used_tools"], decision.tool),
            "step": state["step"] + 1,
            "decision": None,
        }

    def after_tool(state: RuntimeLoopState) -> AfterToolEdge:
        return "exhausted" if state["step"] > max_steps else "plan"

    def finish_node(state: RuntimeLoopState) -> dict[str, object]:
        decision = state["decision"]
        if decision is None or decision.action != "finish":
            raise DynamicWorkflowError("finish node requires a finish decision")

        runtime_step = DynamicRuntimeStep(
            step=state["step"],
            decision=decision,
            result=None,
        )
        return {
            "trace": (*state["trace"], runtime_step),
            "finished": True,
        }

    def exhausted_node(state: RuntimeLoopState) -> dict[str, object]:
        final_evidence = build_runtime_evidence(
            state["results"],
            max_chars=evidence_max_chars,
        )
        raise DynamicWorkflowError(
            f"Dynamic runtime workflow exceeded max_steps={max_steps} "
            f"after tools={list(state['used_tools'])}; "
            f"last evidence chars={len(final_evidence.text)}"
        )

    builder = StateGraph(RuntimeLoopState)
    builder.add_node("plan", plan_node)
    builder.add_node("tool", tool_node)
    builder.add_node("finish", finish_node)
    builder.add_node("exhausted", exhausted_node)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan",
        after_plan,
        {
            "tool": "tool",
            "finish": "finish",
        },
    )
    builder.add_conditional_edges(
        "tool",
        after_tool,
        {
            "plan": "plan",
            "exhausted": "exhausted",
        },
    )
    builder.add_edge("finish", END)
    return builder.compile()


def run_runtime_loop_graph(
    *,
    question: str,
    route: AgentRouteDecision,
    planner_model: ChatModel,
    docker_tools: DockerReadOnlyTools,
    max_steps: int = 4,
    evidence_max_chars: int = 8_000,
) -> DynamicRuntimeResult:
    """Run the Phase 2B node-level loop and return the legacy result contract."""

    if route.route != "runtime_tools":
        raise ValueError("dynamic runtime workflow requires runtime_tools route")
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")

    empty_evidence = build_runtime_evidence((), max_chars=evidence_max_chars)
    initial = RuntimeLoopState(
        question=question,
        route=route,
        results=(),
        evidence=empty_evidence,
        trace=(),
        used_tools=(),
        decision=None,
        step=1,
        finished=False,
    )

    graph = build_runtime_loop_graph(
        planner_model=planner_model,
        docker_tools=docker_tools,
        max_steps=max_steps,
        evidence_max_chars=evidence_max_chars,
    )
    result = graph.invoke(initial)

    if not result["finished"]:
        raise DynamicWorkflowError("runtime loop graph ended without finish")

    return DynamicRuntimeResult(
        results=result["results"],
        evidence=result["evidence"],
        trace=result["trace"],
    )
