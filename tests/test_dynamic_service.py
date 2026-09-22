from docker_agent.agent.dynamic_service import DynamicDockerSupportAgent
from docker_agent.config import Settings
from docker_agent.rag.context import RagContext
from docker_agent.tools.docker_cli import DockerToolResult


class FixedModel:
    def __init__(self, responses: list[str] | str) -> None:
        if isinstance(responses, str):
            responses = [responses]
        self.responses = list(responses)

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        return self.responses.pop(0)


class FakeDockerTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def stats(self, container: str) -> DockerToolResult:
        self.calls.append("docker_stats")
        return DockerToolResult(
            tool="docker_stats",
            command=("docker", "stats", container),
            returncode=0,
            stdout='{"MemUsage":"128MiB / 2GiB"}',
            stderr="",
        )

    def logs(self, container: str, *, tail: int = 100) -> DockerToolResult:
        self.calls.append("docker_logs")
        return DockerToolResult(
            tool="docker_logs",
            command=("docker", "logs", container),
            returncode=0,
            stdout="unexpected",
            stderr="",
        )

    def inspect(self, container: str) -> DockerToolResult:
        raise AssertionError("unexpected inspect")

    def info(self) -> DockerToolResult:
        raise AssertionError("unexpected info")

    def ps(self, *, include_stopped: bool = True) -> DockerToolResult:
        raise AssertionError("unexpected ps")


def test_dynamic_service_ignores_router_tool_plan_and_replans_after_observation() -> None:
    router = FixedModel(
        '{"route":"runtime_tools","reason":"current memory",'
        '"container_ref":"web","tools":["docker_logs"],'
        '"clarification":null,"use_docs":false}'
    )
    planner = FixedModel(
        [
            '{"action":"tool","tool":"docker_stats","reason":"measure memory"}',
            '{"action":"finish","tool":null,"reason":"measurement answers question"}',
        ]
    )
    answer_model = FixedModel("web 当前使用 128MiB 内存。[R1]")
    tools = FakeDockerTools()

    agent = DynamicDockerSupportAgent(
        settings=Settings(),
        router_model=router,
        planner_model=planner,
        answer_model=answer_model,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=lambda _question: RagContext(
            text="",
            sources=(),
            truncated=False,
        ),
    )

    result = agent.handle("web 现在用了多少内存？")

    assert tools.calls == ["docker_stats"]
    assert result.answer is not None
    assert result.answer.runtime_citation_indices == (1,)
    assert [step.decision.action for step in result.runtime_trace] == [
        "tool",
        "finish",
    ]
