from __future__ import annotations

from docker_agent.agent.dynamic_workflow import DynamicRuntimeStep
from docker_agent.agent.evidence import RuntimeEvidenceContext
from docker_agent.core.evidence import (
    Evidence,
    EvidenceBundle,
    EvidenceKind,
    citation_source_to_evidence,
    make_evidence_id,
)
from docker_agent.core.state import AgentStep
from docker_agent.rag.context import RagContext

_CONTEXT_SEPARATOR = "\n\n---\n\n"


def runtime_context_to_evidence_bundle(
    context: RuntimeEvidenceContext,
) -> EvidenceBundle:
    """Convert the legacy runtime context into normalized evidence."""

    if not context.sources:
        if context.text:
            raise ValueError("runtime context has text but no sources")
        return EvidenceBundle(
            items=(),
            text="",
            truncated=context.truncated,
        )

    blocks = _split_blocks(context.text)
    if len(blocks) != len(context.sources):
        raise ValueError(
            "runtime context source count does not match evidence block count"
        )

    items: list[Evidence] = []
    for source, block in zip(context.sources, blocks, strict=True):
        content = _extract_payload(block, marker="Output:")
        label = f"[R{source.index}]"
        status = _extract_header_value(block, key="Status")

        items.append(
            Evidence(
                evidence_id=make_evidence_id(
                    "runtime",
                    source.tool,
                    label,
                    content,
                ),
                kind=EvidenceKind.RUNTIME,
                source=source.tool,
                content=content,
                ok=source.ok,
                citation_label=label,
                metadata={
                    "command": source.command,
                    "legacy_index": source.index,
                    "legacy_status": status,
                },
            )
        )

    return EvidenceBundle(
        items=tuple(items),
        text=context.text,
        truncated=context.truncated,
    )


def rag_context_to_evidence_bundle(context: RagContext) -> EvidenceBundle:
    """Convert the legacy RAG context into normalized knowledge evidence."""

    if not context.sources:
        if context.text:
            raise ValueError("RAG context has text but no sources")
        return EvidenceBundle(
            items=(),
            text="",
            truncated=context.truncated,
        )

    blocks = _split_blocks(context.text)
    if len(blocks) != len(context.sources):
        raise ValueError(
            "RAG context source count does not match evidence block count"
        )

    items = tuple(
        citation_source_to_evidence(
            source,
            content=_extract_payload(block, marker="Content:"),
        )
        for source, block in zip(context.sources, blocks, strict=True)
    )

    return EvidenceBundle(
        items=items,
        text=context.text,
        truncated=context.truncated,
    )


def dynamic_step_to_agent_step(step: DynamicRuntimeStep) -> AgentStep:
    """Convert a legacy dynamic runtime trace step into the core step model."""

    return AgentStep(
        index=step.step,
        action=step.decision.action,
        tool_name=step.decision.tool,
        reason=step.decision.reason,
        ok=step.result.ok if step.result is not None else None,
    )


def dynamic_trace_to_agent_steps(
    trace: tuple[DynamicRuntimeStep, ...],
) -> tuple[AgentStep, ...]:
    return tuple(dynamic_step_to_agent_step(step) for step in trace)


def _split_blocks(text: str) -> tuple[str, ...]:
    if not text.strip():
        return ()
    return tuple(block for block in text.split(_CONTEXT_SEPARATOR) if block)


def _extract_payload(block: str, *, marker: str) -> str:
    token = f"{marker}\n"
    if token not in block:
        raise ValueError(f"context block is missing {marker!r}")

    content = block.split(token, maxsplit=1)[1].strip()
    if not content:
        return "<no output>"
    return content


def _extract_header_value(block: str, *, key: str) -> str | None:
    prefix = f"{key}: "
    for line in block.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip() or None
    return None
