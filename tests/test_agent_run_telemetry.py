import pytest
from sqlalchemy import create_engine

from docker_agent.persistence import (
    AgentRunNotFound,
    AgentRunStateError,
    create_agent_run,
    create_conversation,
    delete_conversation,
    finalize_agent_run_failure,
    finalize_agent_run_success,
    get_agent_run,
    init_persistence_store,
    list_agent_runs,
    safe_error_message,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def test_agent_run_success_lifecycle() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-run-success",
    )

    created = create_agent_run(
        engine,
        conversation_id=conversation.id,
        agent_type="docker_support",
        run_id="run-success",
    )

    assert created.status == "running"
    assert created.completed_at is None
    assert created.duration_ms is None

    completed = finalize_agent_run_success(
        engine,
        created.id,
        route="runtime_tools",
        use_docs=False,
        planned_workers=("runtime", "diagnosis"),
        completed_workers=("runtime", "diagnosis"),
        duration_ms=123,
    )

    assert completed.status == "succeeded"
    assert completed.route == "runtime_tools"
    assert completed.use_docs is False
    assert completed.planned_workers == ("runtime", "diagnosis")
    assert completed.completed_workers == ("runtime", "diagnosis")
    assert completed.duration_ms == 123
    assert completed.error_type is None
    assert completed.error_message is None
    assert completed.completed_at is not None
    assert get_agent_run(engine, created.id) == completed


def test_agent_run_failure_redacts_secret_like_values() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-run-failure",
    )
    created = create_agent_run(
        engine,
        conversation_id=conversation.id,
        agent_type="docker_support",
        run_id="run-failure",
    )

    error = RuntimeError(
        "provider failed api_key=super-secret "
        "Bearer token-value sk-abcdefgh12345678"
    )
    completed = finalize_agent_run_failure(
        engine,
        created.id,
        duration_ms=44,
        error=error,
    )

    assert completed.status == "failed"
    assert completed.error_type == "RuntimeError"
    assert completed.error_message is not None
    assert "super-secret" not in completed.error_message
    assert "token-value" not in completed.error_message
    assert "sk-abcdefgh12345678" not in completed.error_message
    assert "[REDACTED]" in completed.error_message


def test_safe_error_message_is_compact_and_bounded() -> None:
    message = safe_error_message(
        ValueError("line one\nline two " + ("x" * 600)),
        max_chars=80,
    )

    assert message is not None
    assert "\n" not in message
    assert len(message) <= 80
    assert message.endswith("…")


def test_agent_run_cannot_be_finalized_twice() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-run-once",
    )
    created = create_agent_run(
        engine,
        conversation_id=conversation.id,
        agent_type="docker_support",
        run_id="run-once",
    )
    finalize_agent_run_success(
        engine,
        created.id,
        route="docs_only",
        use_docs=True,
        planned_workers=("knowledge", "diagnosis"),
        completed_workers=("knowledge", "diagnosis"),
        duration_ms=10,
    )

    with pytest.raises(AgentRunStateError):
        finalize_agent_run_failure(
            engine,
            created.id,
            duration_ms=11,
            error=RuntimeError("too late"),
        )


def test_list_agent_runs_can_filter_by_conversation() -> None:
    engine = _engine()
    first = create_conversation(
        engine,
        conversation_id="conversation-runs-a",
    )
    second = create_conversation(
        engine,
        conversation_id="conversation-runs-b",
    )
    create_agent_run(
        engine,
        conversation_id=first.id,
        agent_type="docker_support",
        run_id="run-a",
    )
    create_agent_run(
        engine,
        conversation_id=second.id,
        agent_type="docker_support",
        run_id="run-b",
    )

    first_runs = list_agent_runs(
        engine,
        conversation_id=first.id,
    )

    assert [run.id for run in first_runs] == ["run-a"]
    assert {run.id for run in list_agent_runs(engine)} == {
        "run-a",
        "run-b",
    }


def test_deleting_conversation_removes_agent_runs() -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-run-delete",
    )
    run = create_agent_run(
        engine,
        conversation_id=conversation.id,
        agent_type="docker_support",
        run_id="run-delete",
    )

    delete_conversation(engine, conversation.id)

    with pytest.raises(AgentRunNotFound):
        get_agent_run(engine, run.id)
