"""Role-oriented orchestration contracts for the multi-agent upgrade."""

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
    "WorkerRole",
    "plan_workers",
]
