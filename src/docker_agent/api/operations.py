from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from docker_agent.observability import PerformanceSnapshot
from docker_agent.persistence.telemetry import (
    AgentRunRecord,
    AgentRunSummary,
)

AgentRunStatusQuery = Literal["running", "succeeded", "failed"]


class AgentRunResponse(BaseModel):
    id: str
    conversation_id: str
    agent_type: str
    status: AgentRunStatusQuery
    route: str | None
    use_docs: bool | None
    planned_workers: list[str] = Field(default_factory=list)
    completed_workers: list[str] = Field(default_factory=list)
    duration_ms: int | None
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class StagePerformanceResponse(BaseModel):
    stage: str
    count: int
    average_ms: float
    p50_upper_ms: int | None
    p95_upper_ms: int | None


class PerformanceSnapshotResponse(BaseModel):
    ttft_count: int
    ttft_average_ms: float | None
    ttft_p50_upper_ms: int | None
    ttft_p95_upper_ms: int | None
    stages: list[StagePerformanceResponse] = Field(default_factory=list)


class AgentRunSummaryResponse(BaseModel):
    window_started_at: datetime
    window_ended_at: datetime
    total_runs: int
    running_runs: int
    succeeded_runs: int
    failed_runs: int
    success_rate: float | None
    failure_rate: float | None
    duration_p50_ms: int | None
    duration_p95_ms: int | None
    agent_distribution: dict[str, int] = Field(default_factory=dict)
    route_distribution: dict[str, int] = Field(default_factory=dict)
    worker_distribution: dict[str, int] = Field(default_factory=dict)
    error_distribution: dict[str, int] = Field(default_factory=dict)


def build_agent_run_response(
    record: AgentRunRecord,
) -> AgentRunResponse:
    return AgentRunResponse(
        id=record.id,
        conversation_id=record.conversation_id,
        agent_type=record.agent_type,
        status=record.status,
        route=record.route,
        use_docs=record.use_docs,
        planned_workers=list(record.planned_workers),
        completed_workers=list(record.completed_workers),
        duration_ms=record.duration_ms,
        error_type=record.error_type,
        error_message=record.error_message,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def build_performance_snapshot_response(
    snapshot: PerformanceSnapshot,
) -> PerformanceSnapshotResponse:
    return PerformanceSnapshotResponse(
        ttft_count=snapshot.ttft_count,
        ttft_average_ms=snapshot.ttft_average_ms,
        ttft_p50_upper_ms=snapshot.ttft_p50_upper_ms,
        ttft_p95_upper_ms=snapshot.ttft_p95_upper_ms,
        stages=[
            StagePerformanceResponse(
                stage=item.stage,
                count=item.count,
                average_ms=item.average_ms,
                p50_upper_ms=item.p50_upper_ms,
                p95_upper_ms=item.p95_upper_ms,
            )
            for item in snapshot.stages
        ],
    )


def build_agent_run_summary_response(
    summary: AgentRunSummary,
) -> AgentRunSummaryResponse:
    return AgentRunSummaryResponse(
        window_started_at=summary.window_started_at,
        window_ended_at=summary.window_ended_at,
        total_runs=summary.total_runs,
        running_runs=summary.running_runs,
        succeeded_runs=summary.succeeded_runs,
        failed_runs=summary.failed_runs,
        success_rate=summary.success_rate,
        failure_rate=summary.failure_rate,
        duration_p50_ms=summary.duration_p50_ms,
        duration_p95_ms=summary.duration_p95_ms,
        agent_distribution=dict(summary.agent_distribution),
        route_distribution=dict(summary.route_distribution),
        worker_distribution=dict(summary.worker_distribution),
        error_distribution=dict(summary.error_distribution),
    )
