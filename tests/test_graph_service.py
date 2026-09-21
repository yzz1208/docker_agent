from docker_agent.agent.conversation import AgentConversation
from docker_agent.api.chat import build_chat_response
from docker_agent.config import Settings
from docker_agent.graph.service import (
    LangGraphAgentTurnResult,
    LangGraphDockerSupportAgent,
)
from docker_agent.rag.context import RagContext
from docker_agent.tools.docker_cli import DockerToolResult


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.user_prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
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
            stdout='{"MemUsage":"96MiB / 2GiB"}',
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


def test_langgraph_agent_preserves_two_turn_clarification_contract() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"clarify","reason":"missing container",'
                '"container_ref":null,"tools":[],"clarification":"请提供容器名称。",'
                '"use_docs":false}'
            ),
            (
                '{"route":"runtime_tools","reason":"container supplied",'
                '"container_ref":"api-prod","tools":["docker_stats"],'
                '"clarification":null,"use_docs":false}'
            ),
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
                '"reason":"measurement answers the question"}'
            ),
        ]
    )
    answer = SequenceModel(["api-prod 当前使用 96MiB 内存。[R1]"])
    tools = FakeDockerTools()

    agent = LangGraphDockerSupportAgent(
        settings=Settings(),
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=lambda _question: RagContext(
            text="",
            sources=(),
            truncated=False,
        ),
    )
    conversation = AgentConversation(agent)

    first = conversation.handle("这个容器现在用了多少内存？")

    assert isinstance(first, LangGraphAgentTurnResult)
    assert first.needs_clarification is True
    assert first.decision.clarification == "请提供容器名称。"
    assert first.supervisor_plan.workers == ()
    assert first.worker_trace == ()
    assert conversation.state.pending_question == "这个容器现在用了多少内存？"
    assert tools.calls == []
    assert planner.user_prompts == []
    assert answer.user_prompts == []

    second = conversation.handle("api-prod")

    assert isinstance(second, LangGraphAgentTurnResult)
    assert second.needs_clarification is False
    assert second.decision.route == "runtime_tools"
    assert second.decision.container_ref == "api-prod"
    assert second.answer is not None
    assert second.answer.answer == "api-prod 当前使用 96MiB 内存。[R1]"
    assert second.answer.runtime_citation_indices == (1,)
    assert second.supervisor_plan.workers == ("runtime", "diagnosis")
    assert [record.role for record in second.worker_trace] == [
        "runtime",
        "diagnosis",
    ]
    assert second.worker_trace[0].tool_results_added == 1
    assert second.worker_trace[1].answer_created is True
    assert tools.calls == ["docker_stats"]
    assert conversation.state.pending_question is None

    assert len(router.user_prompts) == 2
    assert "这个容器现在用了多少内存？" in router.user_prompts[1]
    assert "User clarification: api-prod" in router.user_prompts[1]


def test_langgraph_agent_handle_graph_exposes_canonical_state() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"runtime_tools","reason":"current memory",'
                '"container_ref":"api-prod","tools":["docker_stats"],'
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
                '"reason":"measurement answers the question"}'
            ),
        ]
    )
    answer = SequenceModel(["api-prod 当前使用 96MiB 内存。[R1]"])
    tools = FakeDockerTools()

    agent = LangGraphDockerSupportAgent(
        settings=Settings(),
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=lambda _question: RagContext(
            text="",
            sources=(),
            truncated=False,
        ),
    )

    graph_state = agent.handle_graph("api-prod 现在用了多少内存？")

    state = graph_state["agent_state"]
    assert state.route == "runtime_tools"
    assert state.container_ref == "api-prod"
    assert len(state.tool_results) == 1
    assert len(state.evidence) == 1
    assert state.evidence[0].citation_label == "[R1]"
    assert [step.action for step in state.runtime_steps] == ["tool", "finish"]
    assert state.answer == "api-prod 当前使用 96MiB 内存。[R1]"
    assert graph_state["supervisor_plan"] is not None
    assert graph_state["supervisor_plan"].workers == (
        "runtime",
        "diagnosis",
    )
    assert [record.role for record in graph_state["worker_trace"]] == [
        "runtime",
        "diagnosis",
    ]


def test_detailed_graph_turn_remains_chat_response_compatible() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"runtime_tools","reason":"current memory",'
                '"container_ref":"api-prod","tools":["docker_stats"],'
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
                '"reason":"measurement answers the question"}'
            ),
        ]
    )
    answer = SequenceModel(["api-prod 当前使用 96MiB 内存。[R1]"])
    tools = FakeDockerTools()
    agent = LangGraphDockerSupportAgent(
        settings=Settings(),
        router_model=router,
        planner_model=planner,
        answer_model=answer,
        docker_tools=tools,  # type: ignore[arg-type]
        docs_retriever=lambda _question: RagContext(
            text="",
            sources=(),
            truncated=False,
        ),
    )

    result = agent.handle("api-prod 现在用了多少内存？")
    response = build_chat_response(
        "session-1",
        False,
        result,
    )

    assert response.route == "runtime_tools"
    assert response.answer == "api-prod 当前使用 96MiB 内存。[R1]"
    assert response.runtime_sources[0].tool == "docker_stats"
