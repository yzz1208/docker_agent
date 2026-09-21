from sqlalchemy import create_engine

from docker_agent.agent.conversation import AgentConversation
from docker_agent.agent.infrastructure import (
    InfrastructureTroubleshooterAgent,
)
from docker_agent.api.chat import ChatSessionManager, build_chat_response
from docker_agent.config import Settings
from docker_agent.persistence import (
    PersistentChatCoordinator,
    init_persistence_store,
    list_agent_runs,
    load_conversation,
)


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.user_prompts: list[str] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


def test_infrastructure_agent_clarifies_vague_incident() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"clarify","reason":"missing affected service",'
                '"clarification":"哪个服务出现了什么具体异常？"}'
            )
        ]
    )
    answer = SequenceModel([])
    agent = InfrastructureTroubleshooterAgent(
        settings=Settings(),
        router_model=router,
        answer_model=answer,
    )

    result = agent.handle("系统有问题")

    assert result.needs_clarification is True
    assert result.decision.route == "clarify"
    assert result.decision.use_docs is False
    assert result.decision.clarification == "哪个服务出现了什么具体异常？"
    assert result.answer is None
    assert result.supervisor_plan.workers == ()
    assert result.worker_trace == ()
    assert answer.user_prompts == []


def test_infrastructure_agent_preserves_clarification_context() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"clarify","reason":"missing symptom",'
                '"clarification":"api 服务具体出现了什么异常？"}'
            ),
            (
                '{"route":"triage","reason":"symptom supplied",'
                '"clarification":null}'
            ),
        ]
    )
    answer = SequenceModel(
        ["已知事实：api 服务持续 503。下一步检查依赖健康度。"]
    )
    conversation = AgentConversation(
        InfrastructureTroubleshooterAgent(
            settings=Settings(),
            router_model=router,
            answer_model=answer,
        )
    )

    first = conversation.handle("api 服务有问题")

    assert first.needs_clarification is True
    assert conversation.state.pending_question == "api 服务有问题"

    second = conversation.handle("从 10:20 开始持续返回 503")

    assert second.needs_clarification is False
    assert second.answer is not None
    assert "503" in second.answer.answer
    assert conversation.state.pending_question is None
    assert "User clarification:" in router.user_prompts[1]
    assert "持续返回 503" in router.user_prompts[1]


def test_infrastructure_agent_triages_user_observations_without_tools() -> None:
    router = SequenceModel(
        [
            (
                '{"route":"triage","reason":"service and symptom supplied",'
                '"clarification":null}'
            )
        ]
    )
    answer = SequenceModel(
        [
            (
                "已知事实：checkout-api 从 10:20 开始大量 503。\n"
                "可能原因：上游依赖异常。\n"
                "下一步：检查同时段依赖错误率。"
            )
        ]
    )
    settings = Settings(
        incident_max_hypotheses=2,
        incident_max_next_steps=3,
    )
    agent = InfrastructureTroubleshooterAgent(
        settings=settings,
        router_model=router,
        answer_model=answer,
    )

    result = agent.handle(
        "checkout-api 从 10:20 开始大量返回 503，刚发布过新版本。"
    )

    assert result.needs_clarification is False
    assert result.decision.route == "triage"
    assert result.decision.use_docs is False
    assert result.answer is not None
    assert "checkout-api" in result.answer.answer
    assert result.answer.doc_sources == ()
    assert result.answer.runtime_sources == ()
    assert result.supervisor_plan.workers == (
        "triage",
        "diagnosis",
    )
    assert [record.role for record in result.worker_trace] == [
        "triage",
        "diagnosis",
    ]
    assert result.worker_trace[1].answer_created is True
    assert "Use at most 2 hypotheses" in answer.user_prompts[0]
    assert "at most 3 next checks" in answer.user_prompts[0]


def test_infrastructure_turn_is_chat_response_compatible() -> None:
    agent = InfrastructureTroubleshooterAgent(
        settings=Settings(),
        router_model=SequenceModel(
            [
                (
                    '{"route":"triage","reason":"enough facts",'
                    '"clarification":null}'
                )
            ]
        ),
        answer_model=SequenceModel(["根因尚未确认，先检查依赖健康度。"]),
    )

    result = agent.handle("api 服务持续 503，依赖超时明显增加。")
    response = build_chat_response(
        "session-infra",
        False,
        result,
        agent_type="infrastructure_troubleshooter",
    )

    assert response.agent_type == "infrastructure_troubleshooter"
    assert response.route == "triage"
    assert response.use_docs is False
    assert response.answer == "根因尚未确认，先检查依赖健康度。"
    assert response.runtime_sources == []
    assert response.doc_sources == []
    assert response.execution is not None
    assert response.execution.planned_workers == [
        "triage",
        "diagnosis",
    ]
    assert response.execution.completed_workers == [
        "triage",
        "diagnosis",
    ]


def test_infrastructure_turn_persists_generic_execution_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    agent = InfrastructureTroubleshooterAgent(
        settings=Settings(),
        router_model=SequenceModel(
            [
                (
                    '{"route":"triage","reason":"enough facts",'
                    '"clarification":null}'
                )
            ]
        ),
        answer_model=SequenceModel(
            ["已知事实：payments-api 延迟升高。下一步检查依赖延迟。"]
        ),
    )
    coordinator = PersistentChatCoordinator(
        engine=engine,
        sessions=ChatSessionManager(
            agent_factory=lambda: agent,
            agent_type="infrastructure_troubleshooter",
        ),
        agent_type="infrastructure_troubleshooter",
    )

    turn = coordinator.chat(
        message="payments-api 从 14:00 开始 P95 延迟升到 3 秒。"
    )

    assert turn.conversation.agent_type == (
        "infrastructure_troubleshooter"
    )
    snapshot = load_conversation(engine, turn.conversation.id)
    assert len(snapshot.messages) == 2
    assert snapshot.messages[1].route == "triage"
    assert snapshot.executions[0].planned_workers == (
        "triage",
        "diagnosis",
    )
    assert snapshot.executions[0].completed_workers == (
        "triage",
        "diagnosis",
    )

    runs = list_agent_runs(
        engine,
        conversation_id=turn.conversation.id,
    )
    assert len(runs) == 1
    assert runs[0].agent_type == "infrastructure_troubleshooter"
    assert runs[0].route == "triage"
    assert runs[0].planned_workers == (
        "triage",
        "diagnosis",
    )
