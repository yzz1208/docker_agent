"""Role-oriented orchestration contracts for the multi-agent upgrade."""

from docker_agent.multi_agent.supervisor import (
    SupervisorPlan,
    WorkerRole,
    plan_workers,
)

__all__ = [
    "SupervisorPlan",
    "WorkerRole",
    "plan_workers",
]
