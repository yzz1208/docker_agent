from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from docker_agent.persistence.evaluation import (
    EvaluationCaseRecord,
    EvaluationRunRecord,
)

EvaluationRunStatusResponse = Literal["running", "succeeded", "failed"]
EvaluationCaseStatusResponse = Literal["passed", "failed", "error"]


class EvaluationRunResponse(BaseModel):
    id: str
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


def build_evaluation_run_response(
    record: EvaluationRunRecord,
) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=record.id,
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
