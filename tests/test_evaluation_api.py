from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from docker_agent.main import app
from docker_agent.persistence import (
    add_evaluation_case,
    create_evaluation_run,
    finalize_evaluation_run_success,
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


def _seed_evaluation(engine: Engine) -> str:
    run = create_evaluation_run(
        engine,
        suite="agent_router",
        agent_type="docker_support",
        dataset_name="agent_router_v1.jsonl",
        dataset_version_value="sha256:abc",
        git_revision="deadbeef",
        config_snapshot={
            "model_name": "router-model",
            "model_api_key": "must-not-store",
        },
        run_id="eval-api-run",
    )
    add_evaluation_case(
        engine,
        evaluation_run_id=run.id,
        case_key="case-1:initial:1",
        case_id="case-1",
        phase="initial",
        repeat=1,
        status="passed",
        metrics={"exact_plan_match": True},
        details={"route": "docs_only"},
    )
    finalize_evaluation_run_success(
        engine,
        run.id,
        aggregate_metrics={
            "cases": 1,
            "overall": {"exact_plan_match_rate": 1.0},
        },
    )
    return run.id


def test_evaluation_runs_list_safe_history(monkeypatch) -> None:
    engine = _engine()
    run_id = _seed_evaluation(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/operations/evaluations")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [run_id]
    assert payload[0]["suite"] == "agent_router"
    assert payload[0]["agent_type"] == "docker_support"
    assert payload[0]["status"] == "succeeded"
    assert payload[0]["case_count"] == 1
    assert payload[0]["passed_count"] == 1
    assert payload[0]["failed_count"] == 0
    assert payload[0]["config_snapshot"]["model_api_key"] == {
        "configured": True,
        "redacted": True,
    }
    assert "must-not-store" not in response.text


def test_evaluation_runs_support_suite_filter_and_pagination(
    monkeypatch,
) -> None:
    engine = _engine()
    _seed_evaluation(engine)
    create_evaluation_run(
        engine,
        suite="agent_workflow",
        agent_type="infrastructure_troubleshooter",
        dataset_name="workflow_v1.jsonl",
        dataset_version_value="sha256:def",
        run_id="eval-workflow",
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    filtered = client.get(
        "/operations/evaluations?suite=agent_router"
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [
        "eval-api-run"
    ]

    agent_filtered = client.get(
        "/operations/evaluations",
        params={"agent_type": "infrastructure_troubleshooter"},
    )
    assert agent_filtered.status_code == 200
    assert [item["id"] for item in agent_filtered.json()] == [
        "eval-workflow"
    ]

    page = client.get("/operations/evaluations?limit=1&offset=1")
    assert page.status_code == 200
    assert len(page.json()) == 1


def test_evaluation_run_detail_includes_cases(monkeypatch) -> None:
    engine = _engine()
    run_id = _seed_evaluation(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(f"/operations/evaluations/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["run"]["aggregate_metrics"]["cases"] == 1
    assert len(payload["cases"]) == 1
    assert payload["cases"][0]["case_key"] == "case-1:initial:1"
    assert payload["cases"][0]["metrics"] == {
        "exact_plan_match": True
    }


def test_evaluation_run_detail_returns_404(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get("/operations/evaluations/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Evaluation run was not found."
    )


def test_evaluation_runs_reject_invalid_pagination(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    bad_limit = client.get("/operations/evaluations?limit=0")
    assert bad_limit.status_code == 400
    assert bad_limit.json()["detail"] == "limit must be positive"

    bad_offset = client.get("/operations/evaluations?offset=-1")
    assert bad_offset.status_code == 400
    assert bad_offset.json()["detail"] == (
        "offset must not be negative"
    )
