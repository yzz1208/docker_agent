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


def _seed_pair(engine: Engine) -> None:
    baseline = create_evaluation_run(
        engine,
        suite="agent_router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:same",
        config_snapshot={"model_name": "router-v1"},
        run_id="baseline-api",
    )
    add_evaluation_case(
        engine,
        evaluation_run_id=baseline.id,
        case_key="case-1",
        case_id="case-1",
        status="passed",
        details={
            "actual": {
                "route": "docs_only",
                "tools": [],
            }
        },
    )
    finalize_evaluation_run_success(
        engine,
        baseline.id,
        aggregate_metrics={
            "overall": {
                "exact_plan_match_rate": 1.0,
            }
        },
    )

    candidate = create_evaluation_run(
        engine,
        suite="agent_router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:same",
        config_snapshot={"model_name": "router-v2"},
        run_id="candidate-api",
    )
    add_evaluation_case(
        engine,
        evaluation_run_id=candidate.id,
        case_key="case-1",
        case_id="case-1",
        status="failed",
        details={
            "actual": {
                "route": "runtime_tools",
                "tools": ["docker_ps"],
            }
        },
    )
    finalize_evaluation_run_success(
        engine,
        candidate.id,
        aggregate_metrics={
            "overall": {
                "exact_plan_match_rate": 0.8,
            }
        },
    )


def test_evaluation_comparison_api_reports_regression(monkeypatch) -> None:
    engine = _engine()
    _seed_pair(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/operations/evaluations/compare",
        params={
            "baseline_id": "baseline-api",
            "candidate_id": "candidate-api",
            "max_regression": 0.02,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "regression"
    assert payload["gate_passed"] is False
    assert payload["new_failures"] == ["case-1"]
    assert payload["new_passes"] == []
    assert payload["common_case_count"] == 1
    assert payload["metric_comparisons"][0]["path"] == (
        "overall.exact_plan_match_rate"
    )
    assert payload["metric_comparisons"][0]["regression"] is True
    assert {
        change["field"]
        for change in payload["behavior_changes"]
    } == {"route", "tools"}
    assert payload["configuration_changes"] == [
        {
            "path": "model_name",
            "baseline_value": "router-v1",
            "candidate_value": "router-v2",
        }
    ]


def test_evaluation_comparison_api_rejects_missing_run(monkeypatch) -> None:
    engine = _engine()
    _seed_pair(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/operations/evaluations/compare",
        params={
            "baseline_id": "missing",
            "candidate_id": "candidate-api",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Evaluation run was not found."
    )


def test_evaluation_comparison_api_rejects_incompatible_runs(
    monkeypatch,
) -> None:
    engine = _engine()
    baseline = create_evaluation_run(
        engine,
        suite="agent_router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:a",
        run_id="baseline-incompatible",
    )
    finalize_evaluation_run_success(
        engine,
        baseline.id,
        aggregate_metrics={},
    )
    candidate = create_evaluation_run(
        engine,
        suite="agent_workflow",
        dataset_name="workflow.jsonl",
        dataset_version_value="sha256:b",
        run_id="candidate-incompatible",
    )
    finalize_evaluation_run_success(
        engine,
        candidate.id,
        aggregate_metrics={},
    )
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/operations/evaluations/compare",
        params={
            "baseline_id": baseline.id,
            "candidate_id": candidate.id,
        },
    )

    assert response.status_code == 400
    assert "suites must match" in response.json()["detail"]


def test_evaluation_comparison_api_rejects_negative_threshold(
    monkeypatch,
) -> None:
    engine = _engine()
    _seed_pair(engine)
    monkeypatch.setattr(
        "docker_agent.main.get_persistence_engine",
        lambda: engine,
    )
    client = TestClient(app)

    response = client.get(
        "/operations/evaluations/compare",
        params={
            "baseline_id": "baseline-api",
            "candidate_id": "candidate-api",
            "max_regression": -0.01,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "max_regression must not be negative"
    )
