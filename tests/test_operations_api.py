from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.main import app
from docker_agent.persistence import (
    create_agent_run,
    create_conversation,
    finalize_agent_run_failure,
    finalize_agent_run_success,
    init_persistence_store,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_persistence_store(engine)
    return engine


def _seed_runs(engine: Engine) -> tuple[str, str, str]:
    first = create_conversation(
        engine,
        conversation_id="conversation-ops-a",
    )
    second = create_conversation(
        engine,
        agent_type="future_agent",
        conversation_id="conversation-ops-b",
    )

    success = create_agent_run(
        engine,
        conversation_id=first.id,
        agent_type="docker_support",
        run_id="run-success",
    )
    finalize_agent_run_success(
        engine,
        success.id,
        route="docs_only",
        use_docs=True,
        planned_workers=("knowledge", "diagnosis"),
        completed_workers=("knowledge", "diagnosis"),
        duration_ms=100,
    )

    failure = create_agent_run(
        engine,
        conversation_id=first.id,
        agent_type="docker_support",
        run_id="run-failure",
    )
    finalize_agent_run_failure(
        engine,
        failure.id,
        route="runtime_tools",
        use_docs=False,
        planned_workers=("runtime", "diagnosis"),
        completed_workers=("runtime",),
        duration_ms=300,
        error=RuntimeError(
            "provider failed api_key=super-secret Bearer token-value"
        ),
    )

    running = create_agent_run(
        engine,
        conversation_id=second.id,
        agent_type="future_agent",
        run_id="run-running",
    )

    return success.id, failure.id, running.id


def test_operations_runs_lists_safe_telemetry(monkeypatch) -> None:
    engine = _engine()
    success_id, failure_id, running_id = _seed_runs(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/operations/runs")

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {
        success_id,
        failure_id,
        running_id,
    }

    failure = next(item for item in payload if item["id"] == failure_id)
    assert failure["status"] == "failed"
    assert failure["error_type"] == "RuntimeError"
    assert "super-secret" not in failure["error_message"]
    assert "token-value" not in failure["error_message"]
    assert "[REDACTED]" in failure["error_message"]


def test_operations_runs_supports_filters_and_pagination(monkeypatch) -> None:
    engine = _engine()
    _seed_runs(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    failed = client.get(
        "/operations/runs?status=failed&agent_type=docker_support"
    )
    assert failed.status_code == 200
    failed_payload = failed.json()
    assert [item["id"] for item in failed_payload] == ["run-failure"]

    conversation = client.get(
        "/operations/runs?conversation_id=conversation-ops-a"
    )
    assert conversation.status_code == 200
    assert {item["id"] for item in conversation.json()} == {
        "run-success",
        "run-failure",
    }

    page = client.get("/operations/runs?limit=1&offset=1")
    assert page.status_code == 200
    assert len(page.json()) == 1


def test_operations_run_detail_and_missing(monkeypatch) -> None:
    engine = _engine()
    success_id, _, _ = _seed_runs(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(f"/operations/runs/{success_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == success_id
    assert payload["route"] == "docs_only"
    assert payload["planned_workers"] == ["knowledge", "diagnosis"]
    assert payload["duration_ms"] == 100

    missing = client.get("/operations/runs/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Agent run was not found."


def test_operations_summary_uses_completed_runs_for_rates_and_latency(
    monkeypatch,
) -> None:
    engine = _engine()
    _seed_runs(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/operations/summary?hours=24")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_runs"] == 3
    assert payload["running_runs"] == 1
    assert payload["succeeded_runs"] == 1
    assert payload["failed_runs"] == 1
    assert payload["success_rate"] == 0.5
    assert payload["failure_rate"] == 0.5
    assert payload["duration_p50_ms"] == 200
    assert payload["duration_p95_ms"] == 290
    assert payload["agent_distribution"] == {
        "docker_support": 2,
        "future_agent": 1,
    }
    assert payload["route_distribution"] == {
        "docs_only": 1,
        "runtime_tools": 1,
    }
    assert payload["worker_distribution"] == {
        "diagnosis": 1,
        "knowledge": 1,
        "runtime": 1,
    }
    assert payload["error_distribution"] == {
        "RuntimeError": 1,
    }




def test_operations_summary_supports_agent_filter(monkeypatch) -> None:
    engine = _engine()
    _seed_runs(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/operations/summary?hours=24&agent_type=docker_support"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_runs"] == 2
    assert payload["running_runs"] == 0
    assert payload["succeeded_runs"] == 1
    assert payload["failed_runs"] == 1
    assert payload["agent_distribution"] == {
        "docker_support": 2,
    }
    assert payload["route_distribution"] == {
        "docs_only": 1,
        "runtime_tools": 1,
    }

def test_operations_summary_handles_no_completed_runs(monkeypatch) -> None:
    engine = _engine()
    conversation = create_conversation(
        engine,
        conversation_id="conversation-only-running",
    )
    create_agent_run(
        engine,
        conversation_id=conversation.id,
        agent_type="docker_support",
        run_id="run-only-running",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/operations/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_runs"] == 1
    assert payload["running_runs"] == 1
    assert payload["success_rate"] is None
    assert payload["failure_rate"] is None
    assert payload["duration_p50_ms"] is None
    assert payload["duration_p95_ms"] is None


def test_operations_api_rejects_invalid_ranges(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    bad_limit = client.get("/operations/runs?limit=0")
    assert bad_limit.status_code == 400
    assert bad_limit.json()["detail"] == "limit must be positive"

    bad_offset = client.get("/operations/runs?offset=-1")
    assert bad_offset.status_code == 400
    assert bad_offset.json()["detail"] == "offset must not be negative"

    bad_hours = client.get("/operations/summary?hours=0")
    assert bad_hours.status_code == 400
    assert bad_hours.json()["detail"] == "hours must be positive"

    too_many_hours = client.get("/operations/summary?hours=721")
    assert too_many_hours.status_code == 400
    assert too_many_hours.json()["detail"] == "hours must not exceed 720"
