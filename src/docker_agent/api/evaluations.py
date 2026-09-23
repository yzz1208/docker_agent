from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from docker_agent.evaluation_comparison import (
    BehaviorChange,
    ConfigurationChange,
    EvaluationComparison,
    MetricComparison,
)
from docker_agent.persistence.evaluation import (
    EvaluationCaseRecord,
    EvaluationRunRecord,
)

EvaluationRunStatusResponse = Literal["running", "succeeded", "failed"]
EvaluationCaseStatusResponse = Literal["passed", "failed", "error"]


class EvaluationRunResponse(BaseModel):
    id: str
    agent_type: str | None
    suite: str
    dataset_name: str
    dataset_version: str
    git_revision: str | None
    status: EvaluationRunStatusResponse
    config_snapshot: dict[str, object] = Field(default_factory=dict)
    aggregate_metrics: dict[str, object] = Field(default_factory=dict)
    case_count: int
    passed_count: int
    failed_count: int
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class EvaluationCaseResponse(BaseModel):
    id: str
    evaluation_run_id: str
    case_key: str
    case_id: str
    phase: str | None
    repeat: int | None
    status: EvaluationCaseStatusResponse
    metrics: dict[str, object] = Field(default_factory=dict)
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class EvaluationRunDetailResponse(BaseModel):
    run: EvaluationRunResponse
    cases: list[EvaluationCaseResponse] = Field(default_factory=list)


class MetricComparisonResponse(BaseModel):
    path: str
    baseline_value: float
    candidate_value: float
    delta: float
    quality_delta: float
    direction: str
    threshold: float
    regression: bool
    improvement: bool


class BehaviorChangeResponse(BaseModel):
    case_key: str
    field: str
    baseline_value: object
    candidate_value: object


class ConfigurationChangeResponse(BaseModel):
    path: str
    baseline_value: object
    candidate_value: object


class EvaluationComparisonResponse(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    agent_type: str | None
    suite: str
    dataset_name: str
    dataset_version: str
    max_regression: float
    verdict: str
    gate_passed: bool
    common_case_count: int
    baseline_only_case_keys: list[str] = Field(default_factory=list)
    candidate_only_case_keys: list[str] = Field(default_factory=list)
    new_failures: list[str] = Field(default_factory=list)
    new_passes: list[str] = Field(default_factory=list)
    unchanged_failures: list[str] = Field(default_factory=list)
    metric_comparisons: list[MetricComparisonResponse] = Field(
        default_factory=list
    )
    behavior_changes: list[BehaviorChangeResponse] = Field(
        default_factory=list
    )
    configuration_changes: list[ConfigurationChangeResponse] = Field(
        default_factory=list
    )


def build_evaluation_run_response(
    record: EvaluationRunRecord,
) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=record.id,
        agent_type=record.agent_type,
        suite=record.suite,
        dataset_name=record.dataset_name,
        dataset_version=record.dataset_version,
        git_revision=record.git_revision,
        status=record.status,
        config_snapshot=dict(record.config_snapshot),
        aggregate_metrics=dict(record.aggregate_metrics),
        case_count=record.case_count,
        passed_count=record.passed_count,
        failed_count=record.failed_count,
        error_type=record.error_type,
        error_message=record.error_message,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def build_evaluation_case_response(
    record: EvaluationCaseRecord,
) -> EvaluationCaseResponse:
    return EvaluationCaseResponse(
        id=record.id,
        evaluation_run_id=record.evaluation_run_id,
        case_key=record.case_key,
        case_id=record.case_id,
        phase=record.phase,
        repeat=record.repeat,
        status=record.status,
        metrics=dict(record.metrics),
        details=dict(record.details),
        created_at=record.created_at,
    )



def build_evaluation_comparison_response(
    comparison: EvaluationComparison,
) -> EvaluationComparisonResponse:
    return EvaluationComparisonResponse(
        baseline_run_id=comparison.baseline_run_id,
        candidate_run_id=comparison.candidate_run_id,
        agent_type=comparison.agent_type,
        suite=comparison.suite,
        dataset_name=comparison.dataset_name,
        dataset_version=comparison.dataset_version,
        max_regression=comparison.max_regression,
        verdict=comparison.verdict,
        gate_passed=comparison.gate_passed,
        common_case_count=comparison.common_case_count,
        baseline_only_case_keys=list(
            comparison.baseline_only_case_keys
        ),
        candidate_only_case_keys=list(
            comparison.candidate_only_case_keys
        ),
        new_failures=list(comparison.new_failures),
        new_passes=list(comparison.new_passes),
        unchanged_failures=list(comparison.unchanged_failures),
        metric_comparisons=[
            _metric_comparison_response(item)
            for item in comparison.metric_comparisons
        ],
        behavior_changes=[
            _behavior_change_response(item)
            for item in comparison.behavior_changes
        ],
        configuration_changes=[
            _configuration_change_response(item)
            for item in comparison.configuration_changes
        ],
    )


def _metric_comparison_response(
    item: MetricComparison,
) -> MetricComparisonResponse:
    return MetricComparisonResponse(
        path=item.path,
        baseline_value=item.baseline_value,
        candidate_value=item.candidate_value,
        delta=item.delta,
        quality_delta=item.quality_delta,
        direction=item.direction,
        threshold=item.threshold,
        regression=item.regression,
        improvement=item.improvement,
    )


def _behavior_change_response(
    item: BehaviorChange,
) -> BehaviorChangeResponse:
    return BehaviorChangeResponse(
        case_key=item.case_key,
        field=item.field,
        baseline_value=item.baseline_value,
        candidate_value=item.candidate_value,
    )


def _configuration_change_response(
    item: ConfigurationChange,
) -> ConfigurationChangeResponse:
    return ConfigurationChangeResponse(
        path=item.path,
        baseline_value=item.baseline_value,
        candidate_value=item.candidate_value,
    )
