from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from docker_agent.core.tool_result import ToolResult

if TYPE_CHECKING:
    from docker_agent.rag.context import CitationSource


class EvidenceKind(StrEnum):
    """Stable evidence categories shared across agent workflows."""

    KNOWLEDGE = "knowledge"
    RUNTIME = "runtime"
    USER = "user"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One normalized piece of evidence available to the agent."""

    evidence_id: str
    kind: EvidenceKind
    source: str
    content: str
    ok: bool
    citation_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if not self.content.strip():
            raise ValueError("content must not be empty")
        if self.citation_label is not None and not self.citation_label.strip():
            raise ValueError("citation_label must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """A normalized evidence collection plus its compatibility text view."""

    items: tuple[Evidence, ...]
    text: str
    truncated: bool = False

    def __post_init__(self) -> None:
        evidence_ids = [item.evidence_id for item in self.items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("EvidenceBundle contains duplicate evidence_id values")

        labels = [
            item.citation_label
            for item in self.items
            if item.citation_label is not None
        ]
        if len(labels) != len(set(labels)):
            raise ValueError("EvidenceBundle contains duplicate citation labels")


def runtime_tool_result_to_evidence(
    result: ToolResult,
    *,
    index: int,
) -> Evidence:
    """Convert a normalized tool result into runtime evidence."""

    if index <= 0:
        raise ValueError("index must be positive")

    label = f"[R{index}]"
    content = result.output.strip()
    if not result.ok:
        content = (result.error or result.output).strip()
    if not content:
        content = "<no output>"

    metadata = dict(result.metadata)
    metadata.update(
        {
            "tool_name": result.tool_name,
            "error_type": result.error_type.value,
        }
    )

    return Evidence(
        evidence_id=_stable_evidence_id(
            "runtime",
            result.tool_name,
            label,
            content,
        ),
        kind=EvidenceKind.RUNTIME,
        source=result.tool_name,
        content=content,
        ok=result.ok,
        citation_label=label,
        metadata=metadata,
    )


def citation_source_to_evidence(
    source: CitationSource,
    *,
    content: str,
) -> Evidence:
    """Convert one RAG citation source into normalized knowledge evidence."""

    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("knowledge evidence content must not be empty")

    label = f"[{source.index}]"
    return Evidence(
        evidence_id=_stable_evidence_id(
            "knowledge",
            source.chunk_id,
            label,
            normalized_content,
        ),
        kind=EvidenceKind.KNOWLEDGE,
        source="docker_docs",
        content=normalized_content,
        ok=True,
        citation_label=label,
        metadata={
            "chunk_id": source.chunk_id,
            "title": source.title,
            "section_path": source.section_path,
            "source_url": source.source_url,
            "file_path": source.file_path,
        },
    )


def user_message_to_evidence(
    content: str,
    *,
    source: str = "user_message",
) -> Evidence:
    """Represent an explicit user statement as first-class evidence."""

    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("user evidence content must not be empty")

    return Evidence(
        evidence_id=_stable_evidence_id(
            "user",
            source,
            normalized_content,
        ),
        kind=EvidenceKind.USER,
        source=source,
        content=normalized_content,
        ok=True,
        citation_label=None,
    )


def _stable_evidence_id(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"ev_{digest}"
