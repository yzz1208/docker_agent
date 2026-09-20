from docker_agent.graph.workflow import run_route_graph


class FakeRouterModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        assert "route Docker support questions" in system_prompt
        assert "User question:" in user_prompt
        return self.response


def test_route_graph_runs_docs_only_path() -> None:
    model = FakeRouterModel(
        """
        {
          "route": "docs_only",
          "reason": "Documentation is sufficient.",
          "container_ref": null,
          "tools": [],
          "clarification": null,
          "use_docs": true
        }
        """
    )

    result = run_route_graph("Docker volume 是什么？", model)

    assert model.calls == 1
    assert result["decision"] is not None
    assert result["decision"].route == "docs_only"
    assert result["agent_state"].route == "docs_only"
    assert result["agent_state"].use_docs is True
    assert result["agent_state"].tool_results == ()
    assert result["agent_state"].evidence == ()


def test_route_graph_preserves_runtime_container_ref() -> None:
    model = FakeRouterModel(
        """
        {
          "route": "runtime_tools",
          "reason": "Current memory requires runtime evidence.",
          "container_ref": "web",
          "tools": ["docker_stats"],
          "clarification": null,
          "use_docs": false
        }
        """
    )

    result = run_route_graph("web 现在用了多少内存？", model)

    assert result["decision"] is not None
    assert result["decision"].route == "runtime_tools"
    assert result["decision"].tools == ("docker_stats",)
    assert result["agent_state"].route == "runtime_tools"
    assert result["agent_state"].container_ref == "web"
    assert result["agent_state"].use_docs is False


def test_route_graph_preserves_clarification_boundary() -> None:
    model = FakeRouterModel(
        """
        {
          "route": "clarify",
          "reason": "A container name is required.",
          "container_ref": null,
          "tools": ["docker_inspect"],
          "clarification": "请提供容器名称或 ID。",
          "use_docs": false
        }
        """
    )

    result = run_route_graph("我的容器为什么退出了？", model)

    assert result["decision"] is not None
    assert result["decision"].route == "clarify"
    assert result["decision"].tools == ()
    assert result["decision"].clarification == "请提供容器名称或 ID。"
    assert result["agent_state"].route == "clarify"
    assert result["agent_state"].container_ref is None


def test_route_graph_rejects_empty_question_before_graph_execution() -> None:
    model = FakeRouterModel("{}")

    try:
        run_route_graph("   ", model)
    except ValueError as exc:
        assert str(exc) == "question must not be empty"
    else:
        raise AssertionError("expected ValueError")

    assert model.calls == 0
