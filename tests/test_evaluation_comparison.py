import pytest
from sqlalchemy import create_engine

from docker_agent.evaluation_comparison import (
    EvaluationComparisonError,
    compare_evaluation_runs,
)
from docker_agent.persistence import (
    add_evaluation_case,
    create_evaluation_run,
    finalize_evaluation_run_success,
    init_persistence_store,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_persistence_store(engine)
    return engine


def _create_completed_run(
    engine,
    *,
    run_id: str,
    aggregate_metrics: dict[str, object],
    cases: list[dict[str, object]],
    suite: str = "agent_router",
    dataset_version_value: str = "sha256:dataset",
    config_snapshot: dict[str, object] | None = None,
) -> None:
    run = create_evaluation_run(
        engine,
        suite=suite,
        dataset_name="agent_router_v1.jsonl",
        dataset_version_value=dataset_version_value,
        config_snapshot=config_snapshot or {},
        run_id=run_id,
    )
    for case in cases:
        add_evaluation_case(
            engine,
            evaluation_run_id=run.id,
            case_key=str(case["case_key"]),
            case_id=str(case["case_id"]),
            status=case["status"],
            metrics=case.get("metrics"),
            details=case.get("details"),
        )
    finalize_evaluation_run_success(
        engine,
        run.id,
        aggregate_metrics=aggregate_metrics,
    )


def test_compare_evaluation_runs_detects_regression_and_case_transitions() -> None:
    engine = _engine()
    _create_completed_run(
        engine,
        run_id="baseline",
        aggregate_metrics={
            "overall": {
                "exact_plan_match_rate": 0.90,
                "error_rate": 0.05,
            }
        },
        config_snapshot={
            "model_name": "router-v1",
            "temperature": 0.0,
        },
        cases=[
            {
                "case_key": "case-1",
                "case_id": "case-1",
                "status": "passed",
                "details": {
                    "actual": {
                        "route": "docs_only",
                        "tools": [],
                    }
                },
            },
            {
                "case_key": "case-2",
                "case_id": "case-2",
                "status": "failed",
                "details": {
                    "actual": {
                        "route": "runtime_tools",
                        "tools": ["docker_ps"],
                    }
                },
            },
        ],
    )
    _create_completed_run(
        engine,
        run_id="candidate",
        aggregate_metrics={
            "overall": {
                "exact_plan_match_rate": 0.82,
                "error_rate": 0.12,
            }
        },
        config_snapshot={
            "model_name": "router-v2",
            "temperature": 0.0,
        },
        cases=[
            {
                "case_key": "case-1",
                "case_id": "case-1",
                "status": "failed",
                "details": {
                    "actual": {
                        "route": "runtime_tools",
                        "tools": ["docker_logs"],
                    }
                },
            },
            {
                "case_key": "case-2",
                "case_id": "case-2",
                "status": "passed",
                "details": {
                    "actual": {
                        "route": "runtime_tools",
                        "tools": ["docker_ps"],
                    }
                },
            },
        ],
    )

    comparison = compare_evaluation_runs(
        engine,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        max_regression=0.02,
    )

    assert comparison.verdict == "regression"
    assert comparison.gate_passed is False
    assert comparison.common_case_count == 2
    assert comparison.new_failures == ("case-1",)
    assert comparison.new_passes == ("case-2",)
    assert comparison.baseline_only_case_keys == ()
    assert comparison.candidate_only_case_keys == ()

    metrics = {
        metric.path: metric
        for metric in comparison.metric_comparisons
    }
    exact_match = metrics["overall.exact_plan_match_rate"]
    assert exact_match.delta == pytest.approx(-0.08)
    assert exact_match.quality_delta == pytest.approx(-0.08)
    assert exact_match.regression is True
    assert exact_match.direction == "higher_is_better"

    error_rate = metrics["overall.error_rate"]
    assert error_rate.delta == pytest.approx(0.07)
    assert error_rate.quality_delta == pytest.approx(-0.07)
    assert error_rate.regression is True
    assert error_rate.direction == "lower_is_better"

    assert {
        (change.case_key, change.field)
        for change in comparison.behavior_changes
    } == {
        ("case-1", "route"),
        ("case-1", "tools"),
    }
    assert comparison.configuration_changes[0].path == "model_name"


def test_compare_evaluation_runs_respects_regression_threshold() -> None:
    engine = _engine()
    cases = [
        {
            "case_key": "case-1",
            "case_id": "case-1",
            "status": "passed",
        }
    ]
    _create_completed_run(
        engine,
        run_id="baseline",
        aggregate_metrics={"exact_match_rate": 0.90},
        cases=cases,
    )
    _create_completed_run(
        engine,
        run_id="candidate",
        aggregate_metrics={"exact_match_rate": 0.87},
        cases=cases,
    )

    comparison = compare_evaluation_runs(
        engine,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
        max_regression=0.05,
    )

    assert comparison.verdict == "pass"
    assert comparison.gate_passed is True
    assert comparison.metric_comparisons[0].regression is False


def test_compare_evaluation_runs_marks_case_set_mismatch_incomplete() -> None:
    engine = _engine()
    _create_completed_run(
        engine,
        run_id="baseline",
        aggregate_metrics={"exact_match_rate": 1.0},
        cases=[
            {
                "case_key": "case-1",
                "case_id": "case-1",
                "status": "passed",
            },
            {
                "case_key": "case-2",
                "case_id": "case-2",
                "status": "passed",
            },
        ],
    )
    _create_completed_run(
        engine,
        run_id="candidate",
        aggregate_metrics={"exact_match_rate": 1.0},
        cases=[
            {
                "case_key": "case-1",
                "case_id": "case-1",
                "status": "passed",
            },
            {
                "case_key": "case-3",
                "case_id": "case-3",
                "status": "passed",
            },
        ],
    )

    comparison = compare_evaluation_runs(
        engine,
        baseline_run_id="baseline",
        candidate_run_id="candidate",
    )

    assert comparison.verdict == "incomplete"
    assert comparison.gate_passed is False
    assert comparison.baseline_only_case_keys == ("case-2",)
    assert comparison.candidate_only_case_keys == ("case-3",)


def test_compare_evaluation_runs_rejects_incompatible_runs() -> None:
    engine = _engine()
    cases = [
        {
            "case_key": "case-1",
            "case_id": "case-1",
            "status": "passed",
        }
    ]
    _create_completed_run(
        engine,
        run_id="baseline",
        aggregate_metrics={"exact_match_rate": 1.0},
        cases=cases,
        suite="agent_router",
        dataset_version_value="sha256:a",
    )
    _create_completed_run(
        engine,
        run_id="candidate",
        aggregate_metrics={"exact_match_rate": 1.0},
        cases=cases,
        suite="agent_workflow",
        dataset_version_value="sha256:a",
    )

    with pytest.raises(
        EvaluationComparisonError,
        match="suites must match",
    ):
        compare_evaluation_runs(
            engine,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
        )


def test_compare_evaluation_runs_rejects_negative_threshold() -> None:
    engine = _engine()

    with pytest.raises(
        ValueError,
        match="must not be negative",
    ):
        compare_evaluation_runs(
            engine,
            baseline_run_id="baseline",
            candidate_run_id="candidate",
            max_regression=-0.01,
        )
