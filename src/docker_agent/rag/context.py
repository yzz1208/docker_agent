from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docker_agent.rag.store import HybridSearchResult


@dataclass(frozen=True, slots=True)
class CitationSource:
    index: int
    chunk_id: str
    title: str
    section_path: tuple[str, ...]
    source_url: str
    file_path: str

    @property
    def section(self) -> str:
        return " > ".join(self.section_path)


@dataclass(frozen=True, slots=True)
class RagContext:
    text: str
    sources: tuple[CitationSource, ...]
    truncated: bool


def build_rag_context(
    results: Sequence[HybridSearchResult],
    *,
    max_sources: int = 5,
    max_chars: int = 14_000,
) -> RagContext:
    """Build citation-numbered context blocks for grounded answer generation."""

    if max_sources <= 0:
        raise ValueError("max_sources must be positive")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    blocks: list[str] = []
    sources: list[CitationSource] = []
    seen_chunk_ids: set[str] = set()
    truncated = False
    used_chars = 0
    separator = "\n\n---\n\n"

    for result in results:
        if len(sources) >= max_sources:
            break
        if result.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(result.chunk_id)

        index = len(sources) + 1
        section = " > ".join(result.section_path)
        header_lines = [f"[{index}]", f"Title: {result.title}"]
        if section:
            header_lines.append(f"Section: {section}")
        header_lines.extend([f"Source: {result.source_url}", "Content:"])
        prefix = "\n".join(header_lines) + "\n"

        separator_cost = len(separator) if blocks else 0
        remaining = max_chars - used_chars - separator_cost
        if remaining <= len(prefix):
            truncated = True
            break

        content = result.content.strip()
        allowed_content = remaining - len(prefix)
        if len(content) > allowed_content:
            content = content[:allowed_content].rstrip()
            truncated = True

        block = prefix + content
        blocks.append(block)
        used_chars += separator_cost + len(block)
        sources.append(
            CitationSource(
                index=index,
                chunk_id=result.chunk_id,
                title=result.title,
                section_path=tuple(result.section_path),
                source_url=result.source_url,
                file_path=result.file_path,
            )
        )
        if truncated:
            break

    return RagContext(
        text=separator.join(blocks),
        sources=tuple(sources),
        truncated=truncated,
    )
