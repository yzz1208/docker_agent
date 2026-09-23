from __future__ import annotations

from dataclasses import dataclass

from docker_agent.orchestration.auto_chat import AutoOrchestrationTurn


@dataclass(frozen=True, slots=True)
class AutoOrchestrationParitySnapshot:
    route: str
    current_agent_type: str | None
    needs_clarification: bool
    synthesized: bool
    answer_present: bool
    clarification_present: bool
    trace_stages: tuple[str, ...]
    trace_agents: tuple[str | None, ...]
    specialist_agents: tuple[str, ...]

    @classmethod
    def from_turn(
        cls,
        turn: AutoOrchestrationTurn,
    ) -> AutoOrchestrationParitySnapshot:
        return cls(
            route=turn.route,
            current_agent_type=turn.current_agent_type,
            needs_clarification=turn.needs_clarification,
            synthesized=turn.synthesized,
            answer_present=turn.answer is not None,
            clarification_present=turn.clarification is not None,
            trace_stages=tuple(item.stage for item in turn.trace),
            trace_agents=tuple(item.agent_type for item in turn.trace),
            specialist_agents=tuple(
                item.agent_type
                for item in turn.specialist_results
            ),
        )


@dataclass(frozen=True, slots=True)
class AutoOrchestrationParityMismatch:
    field: str
    baseline_value: object
    candidate_value: object


@dataclass(frozen=True, slots=True)
class AutoOrchestrationParityReport:
    baseline: AutoOrchestrationParitySnapshot
    candidate: AutoOrchestrationParitySnapshot
    mismatches: tuple[AutoOrchestrationParityMismatch, ...]

    @property
    def gate_passed(self) -> bool:
        return not self.mismatches


def compare_auto_orchestration_turns(
    baseline: AutoOrchestrationTurn,
    candidate: AutoOrchestrationTurn,
) -> AutoOrchestrationParityReport:
    """Compare product-visible Phase 8 and Phase 9 turn structure."""

    baseline_snapshot = AutoOrchestrationParitySnapshot.from_turn(
        baseline
    )
    candidate_snapshot = AutoOrchestrationParitySnapshot.from_turn(
        candidate
    )
    mismatches: list[AutoOrchestrationParityMismatch] = []

    for field in (
        "route",
        "current_agent_type",
        "needs_clarification",
        "synthesized",
        "answer_present",
        "clarification_present",
        "trace_stages",
        "trace_agents",
        "specialist_agents",
    ):
        baseline_value = getattr(baseline_snapshot, field)
        candidate_value = getattr(candidate_snapshot, field)
        if baseline_value != candidate_value:
            mismatches.append(
                AutoOrchestrationParityMismatch(
                    field=field,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                )
            )

    return AutoOrchestrationParityReport(
        baseline=baseline_snapshot,
        candidate=candidate_snapshot,
        mismatches=tuple(mismatches),
    )


__all__ = [
    "AutoOrchestrationParityMismatch",
    "AutoOrchestrationParityReport",
    "AutoOrchestrationParitySnapshot",
    "compare_auto_orchestration_turns",
]
