from pathlib import Path

import pytest
from sqlalchemy import create_engine

from docker_agent.persistence import (
    EvaluationCaseAlreadyExists,
    EvaluationRunStateError,
    add_evaluation_case,
    create_evaluation_run,
    dataset_version,
    finalize_evaluation_run_failure,
    finalize_evaluation_run_success,
    get_evaluation_run,
    init_persistence_store,
    list_evaluation_cases,
    list_evaluation_runs,
    sanitize_evaluation_payload,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def test_dataset_version_uses_sha256(tmp_path: Path) -> None:
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text('{"id":"a"}\n', encoding="utf-8")

    version = dataset_version(dataset)

    assert version.startswith("sha256:")
    assert len(version) == len("sha256:") + 64


def test_sanitize_evaluation_payload_redacts_nested_secrets() -> None:
    sanitized = sanitize_evaluation_payload(
        {
            "model_name": "demo-model",
            "provider": {
                "api_key": "super-secret",
                "token": "",
            },
            "nested": [
                {"password": "pw"},
                {"temperature": 0.1},
            ],
            "validation_error": "provider api_key=secret-value",
        }
    )

    assert sanitized == {
        "model_name": "demo-model",
        "provider": {
            "api_key": {
                "configured": True,
                "redacted": True,
            },
            "token": {
                "configured": False,
                "redacted": True,
            },
        },
        "nested": [
            {
                "password": {
                    "configured": True,
                    "redacted": True,
                }
            },
            {"temperature": 0.1},
        ],
        "validation_error": "provider api_key=[REDACTED]",
    }


def test_evaluation_run_success_lifecycle() -> None:
    engine = _engine()
    run = create_evaluation_run(
        engine,
        suite="agent_router",
        dataset_name="agent_router_v1.jsonl",
        dataset_version_value="sha256:abc",
        git_revision="deadbeef",
        config_snapshot={
            "model_name": "router-model",
            "model_api_key": "must-not-store",
        },
        run_id="eval-success",
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
    add_evaluation_case(
        engine,
        evaluation_run_id=run.id,
        case_key="case-2:initial:1",
        case_id="case-2",
        phase="initial",
        repeat=1,
        status="failed",
        metrics={"exact_plan_match": False},
        details={"reason": "wrong route"},
    )

    completed = finalize_evaluation_run_success(
        engine,
        run.id,
        aggregate_metrics={
            "cases": 2,
            "exact_plan_match_rate": 0.5,
        },
    )

    assert completed.status == "succeeded"
    assert completed.case_count == 2
    assert completed.passed_count == 1
    assert completed.failed_count == 1
    assert completed.aggregate_metrics["exact_plan_match_rate"] == 0.5
    assert completed.completed_at is not None
    assert completed.config_snapshot["model_api_key"] == {
        "configured": True,
        "redacted": True,
    }

    cases = list_evaluation_cases(engine, run.id)
    assert [case.case_key for case in cases] == [
        "case-1:initial:1",
        "case-2:initial:1",
    ]


def test_evaluation_run_failure_records_safe_error() -> None:
    engine = _engine()
    run = create_evaluation_run(
        engine,
        suite="workflow",
        dataset_name="workflow_v1.jsonl",
        dataset_version_value="sha256:def",
        run_id="eval-failure",
    )

    completed = finalize_evaluation_run_failure(
        engine,
        run.id,
        error=RuntimeError(
            "judge failed api_key=super-secret Bearer token-value"
        ),
    )

    assert completed.status == "failed"
    assert completed.error_type == "RuntimeError"
    assert completed.error_message is not None
    assert "super-secret" not in completed.error_message
    assert "token-value" not in completed.error_message
    assert "[REDACTED]" in completed.error_message


def test_evaluation_case_key_is_unique_per_run() -> None:
    engine = _engine()
    run = create_evaluation_run(
        engine,
        suite="router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:1",
    )

    add_evaluation_case(
        engine,
        evaluation_run_id=run.id,
        case_key="case-1:initial:1",
        case_id="case-1",
        status="passed",
    )

    with pytest.raises(EvaluationCaseAlreadyExists):
        add_evaluation_case(
            engine,
            evaluation_run_id=run.id,
            case_key="case-1:initial:1",
            case_id="case-1",
            status="failed",
        )


def test_evaluation_run_cannot_be_finalized_twice() -> None:
    engine = _engine()
    run = create_evaluation_run(
        engine,
        suite="router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:2",
    )
    finalize_evaluation_run_success(
        engine,
        run.id,
        aggregate_metrics={},
    )

    with pytest.raises(EvaluationRunStateError):
        finalize_evaluation_run_failure(
            engine,
            run.id,
            error=RuntimeError("too late"),
        )


def test_list_evaluation_runs_supports_suite_filter() -> None:
    engine = _engine()
    create_evaluation_run(
        engine,
        suite="router",
        dataset_name="router.jsonl",
        dataset_version_value="sha256:a",
        run_id="eval-router",
    )
    create_evaluation_run(
        engine,
        suite="workflow",
        dataset_name="workflow.jsonl",
        dataset_version_value="sha256:b",
        run_id="eval-workflow",
    )

    router_runs = list_evaluation_runs(engine, suite="router")

    assert [run.id for run in router_runs] == ["eval-router"]
    assert {run.id for run in list_evaluation_runs(engine)} == {
        "eval-router",
        "eval-workflow",
    }
    assert get_evaluation_run(engine, "eval-router").suite == "router"
