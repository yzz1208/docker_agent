import pytest

from docker_agent.agent.router import (
    AgentRoutingError,
    parse_route_decision,
    route_question,
)


class FakeModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "Return JSON only" in system_prompt
        assert "User question" in user_prompt
        self.calls += 1
        return self.response


def test_chat_route_carries_no_evidence_or_runtime_plan() -> None:
    decision = parse_route_decision(
        '{"route":"chat","reason":"light conversation",'
        '"container_ref":null,"tools":[],"clarification":null,"use_docs":false}'
    )

    assert decision.route == "chat"
    assert decision.tools == ()
    assert decision.container_ref is None
    assert decision.use_docs is False
    assert decision.clarification is None


def test_route_docs_only_question() -> None:
    model = FakeModel("not-json")

    decision = route_question(
        "Docker volume 和 bind mount 有什么区别？",
        model,
    )

    assert decision.route == "docs_only"
    assert decision.tools == ()
    assert decision.container_ref is None
    assert decision.use_docs is True
    assert model.calls == 0


def test_runtime_word_prevents_docs_fast_path() -> None:
    model = FakeModel(
        '{"route":"runtime_tools","reason":"current runtime",'
        '"container_ref":null,"tools":["docker_info"],'
        '"clarification":null,"use_docs":false}'
    )

    decision = route_question(
        "Docker daemon 现在状态怎么样？",
        model,
    )

    assert decision.route == "runtime_tools"
    assert decision.tools == ("docker_info",)
    assert model.calls == 1


def test_route_named_container_memory_to_stats() -> None:
    decision = parse_route_decision(
        '{"route":"runtime_tools","reason":"current usage",'
        '"container_ref":"docker-agent-postgres",'
        '"tools":["docker_stats"],"clarification":null,"use_docs":false}'
    )

    assert decision.route == "runtime_tools"
    assert decision.container_ref == "docker-agent-postgres"
    assert decision.tools == ("docker_stats",)


def test_route_restart_diagnosis_to_inspect_and_logs() -> None:
    decision = parse_route_decision(
        '{"route":"runtime_tools","reason":"restart diagnosis",'
        '"container_ref":"web","tools":["docker_inspect","docker_logs"],'
        '"clarification":null,"use_docs":false}'
    )

    assert decision.tools == ("docker_inspect", "docker_logs")


def test_container_specific_tool_without_container_is_rejected() -> None:
    with pytest.raises(AgentRoutingError, match="container_ref"):
        parse_route_decision(
            '{"route":"runtime_tools","reason":"needs logs",'
            '"container_ref":null,"tools":["docker_logs"],"clarification":null,"use_docs":false}'
        )


def test_unknown_or_write_tool_is_rejected() -> None:
    with pytest.raises(AgentRoutingError, match="Unsupported Docker tool"):
        parse_route_decision(
            '{"route":"runtime_tools","reason":"fix it",'
            '"container_ref":"web","tools":["docker_restart"],'
            '"clarification":null,"use_docs":false}'
        )


def test_clarify_requires_question_and_no_tools() -> None:
    decision = parse_route_decision(
        '{"route":"clarify","reason":"container missing","container_ref":null,'
        '"tools":[],"clarification":"你指的是哪个容器？","use_docs":false}'
    )

    assert decision.route == "clarify"
    assert decision.clarification == "你指的是哪个容器？"


def test_docs_route_cannot_smuggle_container_or_tools() -> None:
    with pytest.raises(AgentRoutingError):
        parse_route_decision(
            '{"route":"docs_only","reason":"docs",'
            '"container_ref":"web","tools":[],"clarification":null,"use_docs":true}'
        )


def test_route_question_rejects_invented_container_ref() -> None:
    with pytest.raises(AgentRoutingError, match="invented"):
        route_question(
            "这个容器现在用了多少内存？",
            FakeModel(
                '{"route":"runtime_tools","reason":"current usage",'
                '"container_ref":"web","tools":["docker_stats"],'
                '"clarification":null,"use_docs":false}'
            ),
        )


def test_clarify_safely_discards_suggested_tools() -> None:
    decision = parse_route_decision(
        '{"route":"clarify","reason":"container missing","container_ref":null,'
        '"tools":["docker_ps"],"clarification":"请提供容器名。","use_docs":true}'
    )

    assert decision.route == "clarify"
    assert decision.tools == ()
    assert decision.container_ref is None
    assert decision.use_docs is False


def test_runtime_route_can_request_docs_for_remediation() -> None:
    decision = parse_route_decision(
        '{"route":"runtime_tools","reason":"runtime plus remediation",'
        '"container_ref":"web","tools":["docker_logs"],'
        '"clarification":null,"use_docs":true}'
    )

    assert decision.route == "runtime_tools"
    assert decision.use_docs is True
