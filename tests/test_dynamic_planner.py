import pytest

from docker_agent.agent.dynamic_planner import (
    DynamicPlannerError,
    parse_runtime_decision,
)


def test_dynamic_planner_accepts_one_safe_tool() -> None:
    decision = parse_runtime_decision(
        '{"action":"tool","tool":"docker_inspect","reason":"check state"}',
        container_ref="web",
    )

    assert decision.action == "tool"
    assert decision.tool == "docker_inspect"


def test_dynamic_planner_accepts_finish_without_tool() -> None:
    decision = parse_runtime_decision(
        '{"action":"finish","tool":null,"reason":"enough evidence"}',
        container_ref="web",
        used_tools=("docker_inspect",),
    )

    assert decision.action == "finish"
    assert decision.tool is None


def test_dynamic_planner_rejects_write_tool() -> None:
    with pytest.raises(DynamicPlannerError, match="Unsupported Docker tool"):
        parse_runtime_decision(
            '{"action":"tool","tool":"docker_restart","reason":"restart it"}',
            container_ref="web",
        )


def test_dynamic_planner_rejects_repeated_tool() -> None:
    with pytest.raises(DynamicPlannerError, match="repeated"):
        parse_runtime_decision(
            '{"action":"tool","tool":"docker_logs","reason":"read again"}',
            container_ref="web",
            used_tools=("docker_logs",),
        )


def test_dynamic_planner_requires_container_for_container_tool() -> None:
    with pytest.raises(DynamicPlannerError, match="container_ref"):
        parse_runtime_decision(
            '{"action":"tool","tool":"docker_stats","reason":"check memory"}',
            container_ref=None,
        )


def test_dynamic_planner_prompt_distinguishes_restart_mechanism_from_root_cause() -> None:
    from docker_agent.agent.dynamic_planner import PLANNER_SYSTEM_PROMPT

    assert "does not by itself explain why the container process keeps failing" in (
        PLANNER_SYSTEM_PROMPT
    )
    assert "request docker_logs after inspect" in PLANNER_SYSTEM_PROMPT
