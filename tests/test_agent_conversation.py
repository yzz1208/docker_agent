from docker_agent.agent.conversation import AgentConversation
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.agent.service import AgentTurnResult


class FakeAgent:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def handle(self, question: str) -> AgentTurnResult:
        self.questions.append(question)
        if len(self.questions) == 1:
            return AgentTurnResult(
                decision=AgentRouteDecision(
                    route="clarify",
                    reason="missing container",
                    container_ref=None,
                    tools=(),
                    clarification="请提供容器名。",
                    use_docs=False,
                ),
                answer=None,
            )

        return AgentTurnResult(
            decision=AgentRouteDecision(
                route="runtime_tools",
                reason="container supplied",
                container_ref="web",
                tools=("docker_logs",),
                clarification=None,
                use_docs=False,
            ),
            answer=None,
        )


def test_conversation_reuses_pending_question_on_follow_up() -> None:
    agent = FakeAgent()
    conversation = AgentConversation(agent)  # type: ignore[arg-type]

    first = conversation.handle("我的容器为什么一直重启？")

    assert first.needs_clarification is True
    assert conversation.state.pending_question == "我的容器为什么一直重启？"

    second = conversation.handle("web")

    assert second.needs_clarification is False
    assert agent.questions[1] == "我的容器为什么一直重启？\nUser clarification: web"
    assert conversation.state.pending_question is None


def test_conversation_reset_clears_pending_state() -> None:
    agent = FakeAgent()
    conversation = AgentConversation(agent)  # type: ignore[arg-type]

    conversation.handle("我的容器为什么一直重启？")
    conversation.reset()

    assert conversation.state.pending_question is None
