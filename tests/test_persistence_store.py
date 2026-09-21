from sqlalchemy import create_engine

from docker_agent.persistence import (
    ConversationNotFound,
    MessageNotFound,
    append_message,
    create_conversation,
    get_conversation,
    init_persistence_store,
    list_conversations,
    load_conversation,
    save_execution,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def test_persistence_round_trip_conversation_messages_and_execution() -> None:
    engine = _engine()

    conversation = create_conversation(
        engine,
        agent_type="docker_support",
        title="Postgres 容器诊断",
        conversation_id="conversation-1",
    )
    user_message = append_message(
        engine,
        conversation_id=conversation.id,
        role="user",
        content="web 现在用了多少内存？",
        message_id="message-user",
    )
    assistant_message = append_message(
        engine,
        conversation_id=conversation.id,
        role="assistant",
        content="web 当前使用 128MiB 内存。[R1]",
        route="runtime_tools",
        use_docs=False,
        message_id="message-assistant",
    )
    execution = save_execution(
        engine,
        message_id=assistant_message.id,
        planned_workers=("runtime", "diagnosis"),
        completed_workers=("runtime", "diagnosis"),
        worker_trace=(
            {
                "index": 1,
                "role": "runtime",
                "tool_results_added": 1,
                "evidence_added": 1,
                "runtime_steps_added": 2,
                "answer_created": False,
            },
            {
                "index": 2,
                "role": "diagnosis",
                "tool_results_added": 0,
                "evidence_added": 0,
                "runtime_steps_added": 0,
                "answer_created": True,
            },
        ),
        execution_id="execution-1",
    )

    snapshot = load_conversation(engine, conversation.id)

    assert snapshot.conversation.id == "conversation-1"
    assert snapshot.conversation.agent_type == "docker_support"
    assert snapshot.conversation.title == "Postgres 容器诊断"
    assert [message.id for message in snapshot.messages] == [
        user_message.id,
        assistant_message.id,
    ]
    assert snapshot.messages[1].route == "runtime_tools"
    assert snapshot.messages[1].use_docs is False
    assert snapshot.executions == (execution,)
    assert execution.planned_workers == ("runtime", "diagnosis")
    assert execution.completed_workers == ("runtime", "diagnosis")
    assert execution.worker_trace[0]["role"] == "runtime"
    assert execution.worker_trace[1]["answer_created"] is True


def test_persistence_keeps_clarification_as_message_metadata() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-clarify",
    )

    assistant_message = append_message(
        engine,
        conversation_id=conversation.id,
        role="assistant",
        content="请提供容器名称。",
        route="clarify",
        use_docs=False,
        clarification="请提供容器名称。",
    )

    loaded = load_conversation(engine, conversation.id)

    assert loaded.messages == (assistant_message,)
    assert loaded.messages[0].route == "clarify"
    assert loaded.messages[0].clarification == "请提供容器名称。"
    assert loaded.executions == ()


def test_list_and_get_conversations_use_product_records() -> None:
    engine = _engine()
    first = create_conversation(
        engine,
        agent_type="docker_support",
        conversation_id="conversation-a",
    )
    second = create_conversation(
        engine,
        agent_type="future_agent",
        conversation_id="conversation-b",
    )

    loaded = get_conversation(engine, first.id)
    conversations = list_conversations(engine)

    assert loaded == first
    assert {item.id for item in conversations} == {first.id, second.id}
    assert {item.agent_type for item in conversations} == {
        "docker_support",
        "future_agent",
    }


def test_append_message_rejects_unknown_conversation() -> None:
    engine = _engine()

    try:
        append_message(
            engine,
            conversation_id="missing",
            role="user",
            content="hello",
        )
    except ConversationNotFound as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("ConversationNotFound was not raised")


def test_save_execution_rejects_unknown_message() -> None:
    engine = _engine()

    try:
        save_execution(
            engine,
            message_id="missing",
            planned_workers=(),
            completed_workers=(),
            worker_trace=(),
        )
    except MessageNotFound as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("MessageNotFound was not raised")
