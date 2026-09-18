import pytest

from docker_agent.agent.router import (
    AgentRoutingError,
    parse_route_decision,
    route_question,
)


class FakeModel:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "Return JSON only" in system_prompt
        assert "User question" in user_prompt
        return self.response


def test_route_docs_only_question() -> None:
    decision = route_question(
        "Docker volume 和 bind mount 有什么区别？",
        FakeModel(
            '{"route":"docs_only","reason":"concept question",'
            '"container_ref":null,"tools":[],"clarification":null}'
        ),
    )

    assert decision.route == "docs_only"
    assert decision.tools == ()
    assert decision.container_ref is None


def test_route_named_container_memory_to_stats() -> None:
    decision = parse_route_decision(
        '{"route":"runtime_tools","reason":"current usage",'
        '"container_ref":"docker-agent-postgres",'
        '"tools":["docker_stats"],"clarification":null}'
    )

    assert decision.route == "runtime_tools"
    assert decision.container_ref == "docker-agent-postgres"
    assert decision.tools == ("docker_stats",)


def test_route_restart_diagnosis_to_inspect_and_logs() -> None:
    decision = parse_route_decision(
        '{"route":"runtime_tools","reason":"restart diagnosis",'
        '"container_ref":"web","tools":["docker_inspect","docker_logs"],'
        '"clarification":null}'
    )

    assert decision.tools == ("docker_inspect", "docker_logs")


def test_container_specific_tool_without_container_is_rejected() -> None:
    with pytest.raises(AgentRoutingError, match="container_ref"):
        parse_route_decision(
            '{"route":"runtime_tools","reason":"needs logs",'
            '"container_ref":null,"tools":["docker_logs"],"clarification":null}'
        )


def test_unknown_or_write_tool_is_rejected() -> None:
    with pytest.raises(AgentRoutingError, match="Unsupported Docker tool"):
        parse_route_decision(
            '{"route":"runtime_tools","reason":"fix it",'
            '"container_ref":"web","tools":["docker_restart"],"clarification":null}'
        )


def test_clarify_requires_question_and_no_tools() -> None:
    decision = parse_route_decision(
        '{"route":"clarify","reason":"container missing","container_ref":null,'
        '"tools":[],"clarification":"你指的是哪个容器？"}'
    )

    assert decision.route == "clarify"
    assert decision.clarification == "你指的是哪个容器？"


def test_docs_route_cannot_smuggle_container_or_tools() -> None:
    with pytest.raises(AgentRoutingError):
        parse_route_decision(
            '{"route":"docs_only","reason":"docs",'
            '"container_ref":"web","tools":[],"clarification":null}'
        )
