import pytest

from docker_agent.agent.router import AgentRouteDecision
from docker_agent.multi_agent.supervisor import SupervisorPlan, plan_workers


def _decision(
    route: str,
    *,
    use_docs: bool,
    clarification: str | None = None,
) -> AgentRouteDecision:
    tools = ()
    container_ref = None
    if route == "runtime_tools":
        tools = ("docker_info",)
    return AgentRouteDecision(
        route=route,  # type: ignore[arg-type]
        reason="test route",
        container_ref=container_ref,
        tools=tools,
        clarification=clarification,
        use_docs=use_docs,
    )


def test_supervisor_plans_docs_only_workers() -> None:
    plan = plan_workers(_decision("docs_only", use_docs=True))

    assert plan.workers == ("knowledge", "diagnosis")
    assert plan.needs_clarification is False


def test_supervisor_plans_runtime_only_workers() -> None:
    plan = plan_workers(_decision("runtime_tools", use_docs=False))

    assert plan.workers == ("runtime", "diagnosis")


def test_supervisor_plans_runtime_then_knowledge_when_docs_are_needed() -> None:
    plan = plan_workers(_decision("runtime_tools", use_docs=True))

    assert plan.workers == ("runtime", "knowledge", "diagnosis")


def test_supervisor_preserves_clarification_without_workers() -> None:
    plan = plan_workers(
        _decision(
            "clarify",
            use_docs=False,
            clarification="请提供容器名称。",
        )
    )

    assert plan.workers == ()
    assert plan.clarification == "请提供容器名称。"
    assert plan.needs_clarification is True


def test_supervisor_plan_requires_diagnosis_as_final_worker() -> None:
    with pytest.raises(ValueError, match="diagnosis must be the final worker"):
        SupervisorPlan(
            workers=("diagnosis", "runtime"),
            reason="invalid order",
        )


def test_supervisor_plan_rejects_worker_execution_during_clarification() -> None:
    with pytest.raises(
        ValueError,
        match="clarification plan must not execute workers",
    ):
        SupervisorPlan(
            workers=("diagnosis",),
            reason="invalid clarification",
            clarification="需要更多信息",
        )
