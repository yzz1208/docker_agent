from __future__ import annotations

from dataclasses import dataclass

from docker_agent.agent.core_adapters import (
    dynamic_trace_to_agent_steps,
    rag_context_to_evidence_bundle,
    runtime_context_to_evidence_bundle,
)
from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.agent.router import AgentRouteDecision
from docker_agent.core.evidence import (
    EvidenceBundle,
    runtime_tool_result_to_evidence,
)
from docker_agent.core.state import AgentState
from docker_agent.core.tool_result import ToolResult, from_docker_tool_result
from docker_agent.rag.context import RagContext
from docker_agent.tools.docker_cli import DockerToolResult


@dataclass(frozen=True, slots=True)
class CoreShadowReport:
    """Compatibility report while the new core models run beside legacy models."""

    state: AgentState
    runtime_bundle: EvidenceBundle
    docs_bundle: EvidenceBundle
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def build_core_shadow_report(
    *,
    question: str,
    decision: AgentRouteDecision,
    runtime_results: tuple[DockerToolResult, ...],
    runtime_context: RuntimeEvidenceContext,
    docs_context: RagContext,
    runtime_trace: tuple[DynamicRuntimeStep, ...],
    answer: str | None,
) -> CoreShadowReport:
    """Build the new core state without changing the legacy execution path."""

    tool_results = tuple(from_docker_tool_result(item) for item in runtime_results)
    legacy_runtime_bundle = runtime_context_to_evidence_bundle(runtime_context)
    runtime_bundle = _runtime_bundle_from_tool_results(
        tool_results,
        legacy_runtime_bundle,
    )
    docs_bundle = rag_context_to_evidence_bundle(docs_context)
    runtime_steps = dynamic_trace_to_agent_steps(runtime_trace)

    state = AgentState(
        question=question,
        route=decision.route,
        container_ref=decision.container_ref,
        use_docs=decision.use_docs,
        tool_results=tool_results,
        evidence=(*runtime_bundle.items, *docs_bundle.items),
        runtime_steps=runtime_steps,
        answer=answer,
        metadata={"shadow_mode": True},
    )

    issues = [
        *_compare_runtime_bundles(
            legacy=legacy_runtime_bundle,
            normalized=runtime_bundle,
        ),
        *_compare_trace(runtime_trace, runtime_steps),
    ]

    if state.route != decision.route:
        issues.append("state route does not match legacy decision")
    if state.container_ref != decision.container_ref:
        issues.append("state container_ref does not match legacy decision")
    if state.use_docs != decision.use_docs:
        issues.append("state use_docs does not match legacy decision")
    if state.answer != answer:
        issues.append("state answer does not match legacy answer")

    return CoreShadowReport(
        state=state,
        runtime_bundle=runtime_bundle,
        docs_bundle=docs_bundle,
        issues=tuple(issues),
    )


def _runtime_bundle_from_tool_results(
    results: tuple[ToolResult, ...],
    legacy_bundle: EvidenceBundle,
) -> EvidenceBundle:
    visible_count = len(legacy_bundle.items)
    if visible_count > len(results):
        raise ValueError("runtime evidence contains more items than runtime tool results")

    items = tuple(
        runtime_tool_result_to_evidence(result, index=index)
        for index, result in enumerate(results[:visible_count], start=1)
    )
    return EvidenceBundle(
        items=items,
        text=legacy_bundle.text,
        truncated=legacy_bundle.truncated,
    )


def _compare_runtime_bundles(
    *,
    legacy: EvidenceBundle,
    normalized: EvidenceBundle,
) -> list[str]:
    issues: list[str] = []

    if legacy.text != normalized.text:
        issues.append("runtime compatibility text changed")
    if legacy.truncated != normalized.truncated:
        issues.append("runtime truncated flag changed")
    if len(legacy.items) != len(normalized.items):
        issues.append("runtime evidence item count changed")
        return issues

    for index, (old, new) in enumerate(
        zip(legacy.items, normalized.items, strict=True),
        start=1,
    ):
        if old.citation_label != new.citation_label:
            issues.append(f"runtime evidence {index} citation label changed")
        if old.source != new.source:
            issues.append(f"runtime evidence {index} source changed")
        if old.ok != new.ok:
            issues.append(f"runtime evidence {index} success status changed")
        if old.content != new.content:
            issues.append(f"runtime evidence {index} content changed")

    return issues


def _compare_trace(
    legacy: tuple[DynamicRuntimeStep, ...],
    normalized: tuple[object, ...],
) -> list[str]:
    issues: list[str] = []
    if len(legacy) != len(normalized):
        return ["runtime step count changed"]

    for index, (old, new) in enumerate(
        zip(legacy, normalized, strict=True),
        start=1,
    ):
        if getattr(new, "index", None) != old.step:
            issues.append(f"runtime step {index} index changed")
        if getattr(new, "action", None) != old.decision.action:
            issues.append(f"runtime step {index} action changed")
        if getattr(new, "tool_name", None) != old.decision.tool:
            issues.append(f"runtime step {index} tool changed")
        if getattr(new, "reason", None) != old.decision.reason:
            issues.append(f"runtime step {index} reason changed")
        legacy_ok = old.result.ok if old.result is not None else None
        if getattr(new, "ok", None) != legacy_ok:
            issues.append(f"runtime step {index} result status changed")

    return issues
