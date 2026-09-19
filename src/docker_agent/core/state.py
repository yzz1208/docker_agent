from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from docker_agent.core.evidence import Evidence, EvidenceBundle
from docker_agent.core.tool_result import ToolResult


@dataclass(frozen=True, slots=True)
class AgentStep:
    """Normalized trace step independent of any orchestration framework."""

    index: int
    action: str
    tool_name: str | None
    reason: str
    ok: bool | None = None

    def __post_init__(self) -> None:
        if self.index <= 0:
            raise ValueError("AgentStep index must be positive")
        if not self.action.strip():
            raise ValueError("AgentStep action must not be empty")
        if not self.reason.strip():
            raise ValueError("AgentStep reason must not be empty")
        if self.tool_name is not None and not self.tool_name.strip():
            raise ValueError("AgentStep tool_name must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class AgentState:
    """One-turn agent state used by the upgraded core domain layer."""

    question: str
    route: str | None = None
    container_ref: str | None = None
    use_docs: bool = False
    tool_results: tuple[ToolResult, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    runtime_steps: tuple[AgentStep, ...] = ()
    answer: str | None = None
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if self.route is not None and not self.route.strip():
            raise ValueError("route must be non-empty when provided")
        if self.container_ref is not None and not self.container_ref.strip():
            raise ValueError("container_ref must be non-empty when provided")
        if self.answer is not None and not self.answer.strip():
            raise ValueError("answer must be non-empty when provided")

        EvidenceBundle(
            items=self.evidence,
            text="",
            truncated=False,
        )

        step_indices = [step.index for step in self.runtime_steps]
        if len(step_indices) != len(set(step_indices)):
            raise ValueError("AgentState contains duplicate runtime step indices")

    def with_route(
        self,
        route: str,
        *,
        container_ref: str | None = None,
        use_docs: bool = False,
    ) -> AgentState:
        """Return a state updated with the validated routing decision."""

        normalized_route = route.strip()
        if not normalized_route:
            raise ValueError("route must not be empty")
        normalized_ref = None
        if container_ref is not None:
            normalized_ref = container_ref.strip()
            if not normalized_ref:
                raise ValueError("container_ref must not be empty")

        return replace(
            self,
            route=normalized_route,
            container_ref=normalized_ref,
            use_docs=use_docs,
        )

    def append_tool_result(self, result: ToolResult) -> AgentState:
        return replace(
            self,
            tool_results=(*self.tool_results, result),
        )

    def append_evidence(self, item: Evidence) -> AgentState:
        return replace(
            self,
            evidence=(*self.evidence, item),
        )

    def append_runtime_step(self, step: AgentStep) -> AgentState:
        return replace(
            self,
            runtime_steps=(*self.runtime_steps, step),
        )

    def append_error(self, error: str) -> AgentState:
        normalized = error.strip()
        if not normalized:
            raise ValueError("error must not be empty")
        return replace(
            self,
            errors=(*self.errors, normalized),
        )

    def with_answer(self, answer: str) -> AgentState:
        normalized = answer.strip()
        if not normalized:
            raise ValueError("answer must not be empty")
        return replace(self, answer=normalized)
