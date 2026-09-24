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


def test_greeting_fast_path_skips_router_rag_and_runtime() -> None:
    docs_calls: list[str] = []
    docker_tools = FakeDockerTools()

    class UnexpectedModel:
        def complete(self, *, system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("greeting fast path must not call the model")

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=UnexpectedModel(),
        answer_model=UnexpectedModel(),
        docker_tools=docker_tools,  # type: ignore[arg-type]
        docs_retriever=lambda question: docs_calls.append(question) or _docs_context(),
    )

    result = agent.handle("你好")

    assert result.decision.route == "chat"
    assert result.answer is not None
    assert "Docker 支持专家" in result.answer.answer
    assert docs_calls == []
    assert docker_tools.calls == []


def test_self_introduction_fast_path_skips_heavy_retrieval() -> None:
    docs_calls: list[str] = []

    class UnexpectedModel:
        def complete(self, *, system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("self introduction must not call the model")

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=UnexpectedModel(),
        answer_model=UnexpectedModel(),
        docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
        docs_retriever=lambda question: docs_calls.append(question) or _docs_context(),
    )

    result = agent.handle("简单介绍自己")

    assert result.decision.route == "chat"
    assert result.answer is not None
    assert "只读运行时诊断" in result.answer.answer
    assert docs_calls == []


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


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2]


class FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def score(self, query: str, passages) -> list[float]:
        self.calls.append((query, len(passages)))
        return [1.0 for _ in passages]


def test_default_docs_retriever_reuses_heavy_models_and_database_check(
    monkeypatch,
) -> None:
    embedder = FakeEmbedder()
    reranker = FakeReranker()
    engine = object()
    database_checks: list[object] = []

    monkeypatch.setattr(
        service_module,
        "check_database",
        lambda value: database_checks.append(value) or True,
    )
    monkeypatch.setattr(
        service_module,
        "search_similar_chunks",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        service_module,
        "search_keyword_chunks",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        service_module,
        "reciprocal_rank_fusion",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        service_module,
        "rerank_candidates",
        lambda query, candidates, scorer, **kwargs: (
            scorer.score(query, []) and []
        ),
    )
    monkeypatch.setattr(
        service_module,
        "build_rag_context",
        lambda *args, **kwargs: _docs_context(),
    )

    agent = DockerSupportAgent(
        settings=Settings(),
        router_model=FixedModel("{}"),
        answer_model=FixedModel(""),
        docker_tools=FakeDockerTools(),  # type: ignore[arg-type]
        embedder=embedder,  # type: ignore[arg-type]
        reranker=reranker,
        docs_engine=engine,  # type: ignore[arg-type]
    )

    first = agent._retrieve_docs("第一个问题")
    second = agent._retrieve_docs("第二个问题")

    assert first == second == _docs_context()
    assert database_checks == [engine]
    assert embedder.calls == ["第一个问题", "第二个问题"]
    assert reranker.calls == [
        ("第一个问题", 0),
        ("第二个问题", 0),
    ]
