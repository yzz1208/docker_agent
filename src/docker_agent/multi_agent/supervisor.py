from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from docker_agent.agent.router import AgentRouteDecision

WorkerRole = Literal["knowledge", "runtime", "diagnosis"]


@dataclass(frozen=True, slots=True)
class SupervisorPlan:
    """Validated worker sequence for one support turn."""

    workers: tuple[WorkerRole, ...]
    reason: str
    clarification: str | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("SupervisorPlan reason must not be empty")
        if len(self.workers) != len(set(self.workers)):
            raise ValueError("SupervisorPlan workers must not contain duplicates")
        if self.clarification is not None:
            if not self.clarification.strip():
                raise ValueError("clarification must be non-empty when provided")
            if self.workers:
                raise ValueError("clarification plan must not execute workers")
        elif not self.workers:
            raise ValueError("non-clarification plan requires at least one worker")

        if self.workers and self.workers[-1] != "diagnosis":
            raise ValueError("diagnosis must be the final worker")

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


def plan_workers(decision: AgentRouteDecision) -> SupervisorPlan:
    """Map the validated legacy route into a deterministic multi-agent worker plan."""

    if decision.route == "clarify":
        if decision.clarification is None:
            raise ValueError("clarify route requires clarification text")
        return SupervisorPlan(
            workers=(),
            reason=decision.reason,
            clarification=decision.clarification,
        )

    if decision.route == "general_chat":
        workers: tuple[WorkerRole, ...] = ("diagnosis",)
    elif decision.route == "docs_only":
        workers = ("knowledge", "diagnosis")
    elif decision.route == "runtime_tools":
        workers = (
            ("runtime", "knowledge", "diagnosis")
            if decision.use_docs
            else ("runtime", "diagnosis")
        )
    else:
        raise ValueError(f"unsupported route: {decision.route}")

    return SupervisorPlan(
        workers=workers,
        reason=decision.reason,
    )
