from docker_agent.graph.workflow import run_support_graph
from docker_agent.rag.context import CitationSource, RagContext
from docker_agent.tools.docker_cli import DockerToolResult


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.responses.pop(0)


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
                    chunk_id="volume-1",
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


def test_supervisor_drives_docs_only_worker_sequence() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"docs_only","reason":"docs are sufficient",'
                '"container_ref":null,"tools":[],"clarification":null,'
                '"use_docs":true}'
            )
        ]
    )
    planner = SequenceModel([])
    answer = SequenceModel(["Docker volume 由 Docker 管理。[1]"])
    docs = FakeDocsRetriever()
    tools = FakeDockerTools()

    result = run_support_graph(
        "Docker volume 是什么？",
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=docs,
    )

    plan = result["supervisor_plan"]
    assert plan is not None
    assert plan.workers == ("knowledge", "diagnosis")
    assert result["completed_workers"] == ("knowledge", "diagnosis")
    assert result["worker_index"] == 2
    assert [record.role for record in result["worker_trace"]] == [
        "knowledge",
        "diagnosis",
    ]
    assert result["worker_trace"][0].evidence_added == 1
    assert result["worker_trace"][0].tool_results_added == 0
    assert result["worker_trace"][1].answer_created is True
    assert docs.calls == ["Docker volume 是什么？"]
    assert tools.calls == []
    assert planner.calls == 0
    assert answer.calls == 1


def test_supervisor_drives_runtime_only_worker_sequence() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"runtime_tools","reason":"runtime required",'
                '"container_ref":"web","tools":["docker_stats"],'
                '"clarification":null,"use_docs":false}'
            )
        ]
    )
    planner = SequenceModel(
        [
            (
                '{"action":"tool","tool":"docker_stats",'
                '"reason":"measure current memory"}'
            ),
            (
                '{"action":"finish","tool":null,'
                '"reason":"measurement is enough"}'
            ),
        ]
    )
    answer = SequenceModel(["web 当前使用 128MiB 内存。[R1]"])
    docs = FakeDocsRetriever()
    tools = FakeDockerTools()

    result = run_support_graph(
        "web 现在用了多少内存？",
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=docs,
    )

    plan = result["supervisor_plan"]
    assert plan is not None
    assert plan.workers == ("runtime", "diagnosis")
    assert result["completed_workers"] == ("runtime", "diagnosis")
    assert result["worker_index"] == 2
    assert [record.role for record in result["worker_trace"]] == [
        "runtime",
        "diagnosis",
    ]
    runtime_record = result["worker_trace"][0]
    assert runtime_record.tool_results_added == 1
    assert runtime_record.evidence_added == 1
    assert runtime_record.runtime_steps_added == 2
    assert result["worker_trace"][1].answer_created is True
    assert tools.calls == ["docker_stats"]
    assert docs.calls == []
    assert answer.calls == 1


def test_supervisor_drives_runtime_then_knowledge_then_diagnosis() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"runtime_tools","reason":"runtime and docs required",'
                '"container_ref":"web","tools":["docker_stats"],'
                '"clarification":null,"use_docs":true}'
            )
        ]
    )
    planner = SequenceModel(
        [
            (
                '{"action":"tool","tool":"docker_stats",'
                '"reason":"measure current memory"}'
            ),
            (
                '{"action":"finish","tool":null,'
                '"reason":"runtime evidence is enough"}'
            ),
        ]
    )
    answer = SequenceModel(
        ["web 当前使用 128MiB 内存。[R1] Docker volume 由 Docker 管理。[1]"]
    )
    docs = FakeDocsRetriever()
    tools = FakeDockerTools()
    question = "web 当前资源情况如何，并说明 Docker volume？"

    result = run_support_graph(
        question,
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=docs,
    )

    plan = result["supervisor_plan"]
    assert plan is not None
    assert plan.workers == ("runtime", "knowledge", "diagnosis")
    assert result["completed_workers"] == (
        "runtime",
        "knowledge",
        "diagnosis",
    )
    assert result["worker_index"] == 3
    assert [record.role for record in result["worker_trace"]] == [
        "runtime",
        "knowledge",
        "diagnosis",
    ]
    assert result["worker_trace"][0].tool_results_added == 1
    assert result["worker_trace"][1].evidence_added == 1
    assert result["worker_trace"][2].answer_created is True
    assert tools.calls == ["docker_stats"]
    assert docs.calls == [question]
    assert answer.calls == 1


def test_supervisor_clarification_plan_executes_no_workers() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"clarify","reason":"container is missing",'
                '"container_ref":null,"tools":[],'
                '"clarification":"请提供容器名称。","use_docs":false}'
            )
        ]
    )
    planner = SequenceModel([])
    answer = SequenceModel([])
    docs = FakeDocsRetriever()
    tools = FakeDockerTools()

    result = run_support_graph(
        "我的容器为什么退出了？",
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=docs,
    )

    plan = result["supervisor_plan"]
    assert plan is not None
    assert plan.workers == ()
    assert plan.clarification == "请提供容器名称。"
    assert result["completed_workers"] == ()
    assert result["worker_index"] == 0
    assert result["worker_trace"] == ()
    assert result["answer"] is None
    assert tools.calls == []
    assert docs.calls == []
    assert planner.calls == 0
    assert answer.calls == 0
