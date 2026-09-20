import pytest

from docker_agent.core.evidence import EvidenceKind
from docker_agent.graph.workflow import run_docs_only_graph, run_route_graph
from docker_agent.rag.context import CitationSource, RagContext


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



class FakeAnswerModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0
        self.last_user_prompt = ""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.last_user_prompt = user_prompt
        assert "Docker technical support agent" in system_prompt
        return self.response


class FakeDocsRetriever:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, question: str) -> RagContext:
        self.calls.append(question)
        return RagContext(
            text=(
                "[1]\n"
                "Title: Volumes\n"
                "Section: Storage > Volumes\n"
                "Source: https://docs.docker.com/engine/storage/volumes/\n"
                "Content:\n"
                "Volumes are managed by Docker."
            ),
            sources=(
                CitationSource(
                    index=1,
                    chunk_id="volumes-1",
                    title="Volumes",
                    section_path=("Storage", "Volumes"),
                    source_url=(
                        "https://docs.docker.com/engine/storage/volumes/"
                    ),
                    file_path="content/manuals/engine/storage/volumes.md",
                ),
            ),
            truncated=False,
        )


def test_docs_only_graph_runs_docs_and_answer_nodes() -> None:
    router = FakeRouterModel(
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
    answer = FakeAnswerModel("Docker volume 由 Docker 管理。[1]")
    docs = FakeDocsRetriever()

    result = run_docs_only_graph(
        "Docker volume 是什么？",
        router_model=router,
        answer_model=answer,
        docs_retriever=docs,
    )

    assert router.calls == 1
    assert docs.calls == ["Docker volume 是什么？"]
    assert answer.calls == 1
    assert "[1]" in answer.last_user_prompt
    assert result["decision"] is not None
    assert result["decision"].route == "docs_only"
    assert result["docs_context"] is not None
    assert result["answer"] is not None
    assert result["answer"].doc_citation_indices == (1,)
    assert result["agent_state"].answer == "Docker volume 由 Docker 管理。[1]"
    assert len(result["agent_state"].evidence) == 1
    assert result["agent_state"].evidence[0].kind is EvidenceKind.KNOWLEDGE
    assert result["agent_state"].evidence[0].citation_label == "[1]"


@pytest.mark.parametrize(
    ("router_response", "question", "expected_route"),
    [
        (
            """
            {
              "route": "runtime_tools",
              "reason": "Current state requires runtime evidence.",
              "container_ref": "web",
              "tools": ["docker_stats"],
              "clarification": null,
              "use_docs": false
            }
            """,
            "web 现在用了多少内存？",
            "runtime_tools",
        ),
        (
            """
            {
              "route": "clarify",
              "reason": "A container name is required.",
              "container_ref": null,
              "tools": ["docker_inspect"],
              "clarification": "请提供容器名称或 ID。",
              "use_docs": false
            }
            """,
            "我的容器为什么退出了？",
            "clarify",
        ),
    ],
)
def test_docs_only_graph_skips_docs_for_other_routes(
    router_response: str,
    question: str,
    expected_route: str,
) -> None:
    router = FakeRouterModel(router_response)
    answer = FakeAnswerModel("should not be called")
    docs = FakeDocsRetriever()

    result = run_docs_only_graph(
        question,
        router_model=router,
        answer_model=answer,
        docs_retriever=docs,
    )

    assert result["decision"] is not None
    assert result["decision"].route == expected_route
    assert docs.calls == []
    assert answer.calls == 0
    assert result["docs_context"] is None
    assert result["answer"] is None
    assert result["agent_state"].answer is None


def test_docs_only_graph_requires_documentation_citation() -> None:
    router = FakeRouterModel(
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
    answer = FakeAnswerModel("Docker volume 由 Docker 管理。")
    docs = FakeDocsRetriever()

    with pytest.raises(
        ValueError,
        match="did not cite Docker documentation evidence",
    ):
        run_docs_only_graph(
            "Docker volume 是什么？",
            router_model=router,
            answer_model=answer,
            docs_retriever=docs,
        )
