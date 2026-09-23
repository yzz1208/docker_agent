from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.core.evidence import EvidenceKind
from docker_agent.core.state import AgentState
from docker_agent.multi_agent.workers import (
    DiagnosisWorker,
    KnowledgeWorker,
    RuntimeWorker,
)
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.tools.docker_cli import DockerToolResult


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.responses.pop(0)


class FakeDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append("docker_stats")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", "--no-stream", container),
            returncode=0,
            stdout='{"MemUsage":"128MiB / 2GiB"}',
            stderr="",
        )

    def inspect(self, container: str) -> DockerToolResult:
        raise AssertionError("unexpected docker_inspect")

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        raise AssertionError("unexpected docker_logs")

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected docker_info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        raise AssertionError("unexpected docker_ps")


def _docs_context() -> RagContext:
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
                chunk_id="volume-1",
                title="Volumes",
                section_path=("Storage", "Volumes"),
                source_url="https://docs.docker.com/engine/storage/volumes/",
                file_path="content/manuals/engine/storage/volumes.md",
            ),
        ),
        truncated=False,
    )


def _runtime_decision(*, use_docs: bool = False) -> AgentRouteDecision:
    return AgentRouteDecision(
        route="runtime_tools",
        reason="runtime evidence required",
        container_ref="web",
        tools=("docker_stats",),
        clarification=None,
        use_docs=use_docs,
    )


def test_knowledge_worker_appends_only_knowledge_evidence() -> None:
    calls: list[str] = []

    def retrieve(question: str) -> RagContext:
        calls.append(question)
        return _docs_context()

    worker = KnowledgeWorker(retrieve)
    state = AgentState(question="Docker volume 是什么？").with_route(
        "docs_only",
        use_docs=True,
    )

    result = worker.run(state)

    assert calls == ["Docker volume 是什么？"]
    assert result.context == _docs_context()
    assert len(result.state.evidence) == 1
    assert result.state.evidence[0].kind is EvidenceKind.KNOWLEDGE
    assert result.state.evidence[0].citation_label == "[1]"
    assert result.state.tool_results == ()
    assert result.state.runtime_steps == ()


def test_runtime_worker_collects_runtime_state_without_answering() -> None:
    planner = SequenceModel(
        [
            (
                '{"action":"tool","tool":"docker_stats",'
                '"reason":"measure current memory"}'
            ),
            (
                '{"action":"finish","tool":null,'
                '"reason":"measurement answers the question"}'
            ),
        ]
    )
    tools = FakeDockerTools()
    worker = RuntimeWorker(
        planner_model=planner,
        docker_tools=tools,  # type: ignore[arg-type]
    )
    state = AgentState(question="web 现在用了多少内存？").with_route(
        "runtime_tools",
        container_ref="web",
        use_docs=False,
    )

    result = worker.run(state, _runtime_decision())

    assert tools.calls == ["docker_stats"]
    assert planner.calls == 2
    assert len(result.state.tool_results) == 1
    assert result.state.tool_results[0].tool_name == "docker_stats"
    assert len(result.state.evidence) == 1
    assert result.state.evidence[0].kind is EvidenceKind.RUNTIME
    assert result.state.evidence[0].citation_label == "[R1]"
    assert [step.action for step in result.state.runtime_steps] == [
        "tool",
        "finish",
    ]
    assert result.state.answer is None


def test_diagnosis_worker_handles_general_chat_without_evidence() -> None:
    model = SequenceModel(
        ["你好，我可以帮助你进行 Docker 支持和故障排查。"]
    )
    worker = DiagnosisWorker(model)
    state = AgentState(question="你好，介绍一下自己").with_route(
        "general_chat",
        use_docs=False,
    )
    decision = AgentRouteDecision(
        route="general_chat",
        reason="greeting",
        container_ref=None,
        tools=(),
        clarification=None,
        use_docs=False,
    )

    result = worker.run(state, decision)

    assert model.calls == 0
    assert result.answer.doc_sources == ()
    assert result.answer.runtime_sources == ()
    assert "Docker 智能支持平台" in result.state.answer


def test_diagnosis_worker_generates_docs_only_answer() -> None:
    model = SequenceModel(["Docker volume 由 Docker 管理。[1]"])
    worker = DiagnosisWorker(model)
    state = AgentState(question="Docker volume 是什么？").with_route(
        "docs_only",
        use_docs=True,
    )
    decision = AgentRouteDecision(
        route="docs_only",
        reason="docs are sufficient",
        container_ref=None,
        tools=(),
        clarification=None,
        use_docs=True,
    )

    result = worker.run(
        state,
        decision,
        docs_context=_docs_context(),
    )

    assert model.calls == 1
    assert result.answer.doc_citation_indices == (1,)
    assert result.answer.runtime_citation_indices == ()
    assert result.state.answer == "Docker volume 由 Docker 管理。[1]"


def test_diagnosis_worker_generates_runtime_answer() -> None:
    planner = SequenceModel(
        [
            (
                '{"action":"tool","tool":"docker_stats",'
                '"reason":"measure current memory"}'
            ),
            (
                '{"action":"finish","tool":null,'
                '"reason":"measurement answers the question"}'
            ),
        ]
    )
    tools = FakeDockerTools()
    runtime_worker = RuntimeWorker(
        planner_model=planner,
        docker_tools=tools,  # type: ignore[arg-type]
    )
    state = AgentState(question="web 现在用了多少内存？").with_route(
        "runtime_tools",
        container_ref="web",
        use_docs=False,
    )
    decision = _runtime_decision()
    runtime_result = runtime_worker.run(state, decision)

    diagnosis = DiagnosisWorker(
        SequenceModel(["web 当前使用 128MiB 内存。[R1]"])
    )
    result = diagnosis.run(
        runtime_result.state,
        decision,
        runtime_context=runtime_result.context,
    )

    assert result.answer.runtime_citation_indices == (1,)
    assert result.answer.doc_citation_indices == ()
    assert result.state.answer == "web 当前使用 128MiB 内存。[R1]"


def test_diagnosis_worker_uses_empty_missing_context_type() -> None:
    model = SequenceModel(["Docker volume 由 Docker 管理。[1]"])
    worker = DiagnosisWorker(model)
    state = AgentState(question="Docker volume 是什么？").with_route(
        "docs_only",
        use_docs=True,
    )
    decision = AgentRouteDecision(
        route="docs_only",
        reason="docs are sufficient",
        container_ref=None,
        tools=(),
        clarification=None,
        use_docs=True,
    )

    result = worker.run(
        state,
        decision,
        docs_context=_docs_context(),
        runtime_context=RuntimeEvidenceContext(
            text="",
            sources=(),
            truncated=False,
        ),
    )

    assert result.answer.doc_citation_indices == (1,)
