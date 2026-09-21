"""Role-oriented orchestration contracts for the multi-agent upgrade."""

from docker_agent.multi_agent.execution import (
    WorkerExecutionRecord,
    build_worker_execution_record,
)
from docker_agent.multi_agent.supervisor import (
    SupervisorPlan,
    WorkerRole,
    plan_workers,
)
from docker_agent.multi_agent.workers import (
    DiagnosisWorker,
    DiagnosisWorkerResult,
    KnowledgeWorker,
    KnowledgeWorkerResult,
    RuntimeWorker,
    RuntimeWorkerResult,
)

__all__ = [
    "DiagnosisWorker",
    "DiagnosisWorkerResult",
    "KnowledgeWorker",
    "KnowledgeWorkerResult",
    "RuntimeWorker",
    "RuntimeWorkerResult",
    "SupervisorPlan",
    "WorkerExecutionRecord",
    "WorkerRole",
    "build_worker_execution_record",
    "plan_workers",
]
