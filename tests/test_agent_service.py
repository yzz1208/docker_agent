import docker_agent.agent.service as service_module
from docker_agent.agent.service import DockerSupportAgent
from docker_agent.config import Settings
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.tools.docker_cli import DockerToolResult


class FixedModel:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return self.response


class FakeDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append(f"stats:{container}")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", container),
            returncode=0,
            stdout='{"MemUsage":"64MiB / 1GiB"}',
            stderr="",
        )

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        raise AssertionError("unexpected ps")

    def inspect(self, container: str) -> DockerToolResult:
        raise AssertionError("unexpected inspect")

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        raise AssertionError("unexpected logs")


def _docs_context() -> RagContext:
    return RagContext(
        text="[1]\nTitle: Volumes\nContent:\nVolumes are managed by Docker.",
        sources=(
            CitationSource(
                index=1,
                chunk_id="chunk-1",
                title="Volumes",
                section_path=("Volumes",),
                source_url="https://docs.docker.com/engine/storage/volumes/",
                file_path="volumes.md",
            ),
        ),
        truncated=False,
    )


def test_runtime_only_route_skips_docs_retrieval() -> None:
    docs_calls: list[str] = []
    docker_tools = FakeDockerTools()
    router = FixedModel(
        '{"route":"runtime_tools","reason":"current usage",'
        '"container_ref":"web","tools":["docker_stats"],'
        '"clarification":null,"use_docs":false}'
    )
    answer_model = FixedModel("当前使用 64MiB。[R1]")

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=router,
        answer_model=answer_model,
        docker_tools=docker_tools,  # type: ignore[arg-type]
        docs_retriever=lambda question: docs_calls.append(question) or _docs_context(),
    )

    result = agent.handle("web 现在用了多少内存？")

    assert docs_calls == []
    assert docker_tools.calls == ["stats:web"]
    assert result.answer is not None
    assert result.answer.runtime_citation_indices == (1,)


def test_docs_only_route_uses_docs_and_no_runtime_tools() -> None:
    docs_calls: list[str] = []
    docker_tools = FakeDockerTools()
    router = FixedModel(
        '{"route":"docs_only","reason":"concept",'
        '"container_ref":null,"tools":[],"clarification":null,"use_docs":true}'
    )
    answer_model = FixedModel("Volume 由 Docker 管理。[1]")

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=router,
        answer_model=answer_model,
        docker_tools=docker_tools,  # type: ignore[arg-type]
        docs_retriever=lambda question: docs_calls.append(question) or _docs_context(),
    )

    result = agent.handle("Docker volume 是什么？")

    assert docs_calls == ["Docker volume 是什么？"]
    assert docker_tools.calls == []
    assert result.answer is not None
    assert result.answer.doc_citation_indices == (1,)


def test_default_rag_resources_are_reused_across_requests(
    monkeypatch,
) -> None:
    created = {
        "engine": 0,
        "embedder": 0,
        "reranker": 0,
    }

    class FakeEngine:
        pass

    class FakeEmbedder:
        def __init__(self) -> None:
            created["embedder"] += 1

    class FakeReranker:
        def __init__(self) -> None:
            created["reranker"] += 1

    def fake_engine():
        created["engine"] += 1
        return FakeEngine()

    monkeypatch.setattr(
        service_module,
        "create_db_engine",
        fake_engine,
    )
    monkeypatch.setattr(
        service_module,
        "check_database",
        lambda engine: True,
    )
    monkeypatch.setattr(
        service_module,
        "BgeM3Embedder",
        FakeEmbedder,
    )
    monkeypatch.setattr(
        service_module,
        "BgeReranker",
        FakeReranker,
    )

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=FixedModel("{}"),
        answer_model=FixedModel("answer"),
        docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
    )

    first_engine = agent._get_docs_engine()
    second_engine = agent._get_docs_engine()
    first_embedder = agent._get_embedder()
    second_embedder = agent._get_embedder()
    first_reranker = agent._get_reranker()
    second_reranker = agent._get_reranker()

    assert first_engine is second_engine
    assert first_embedder is second_embedder
    assert first_reranker is second_reranker
    assert created == {
        "engine": 1,
        "embedder": 1,
        "reranker": 1,
    }
