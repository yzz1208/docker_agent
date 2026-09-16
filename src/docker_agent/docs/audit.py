from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_SHORTCODE_TOKEN_RE = re.compile(r"\{\{[%<].*?[>%]\}\}")


@dataclass(slots=True)
class AuditExample:
    chunk_id: str
    reason: str
    preview: str

    def to_dict(self) -> dict[str, str]:
        return {
            "chunk_id": self.chunk_id,
            "reason": self.reason,
            "preview": self.preview,
        }


@dataclass(slots=True)
class ChunkAuditReport:
    total_chunks: int = 0
    unique_documents: int = 0
    min_words: int = 0
    p50_words: int = 0
    p90_words: int = 0
    p95_words: int = 0
    max_words: int = 0
    average_words: float = 0.0
    tiny_chunks: int = 0
    oversized_chunks: int = 0
    empty_chunks: int = 0
    missing_source_url: int = 0
    missing_section_path: int = 0
    unbalanced_code_fences: int = 0
    shortcode_remnants: int = 0
    duplicate_contents: int = 0
    examples: list[AuditExample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_chunks": self.total_chunks,
            "unique_documents": self.unique_documents,
            "word_count": {
                "min": self.min_words,
                "p50": self.p50_words,
                "p90": self.p90_words,
                "p95": self.p95_words,
                "max": self.max_words,
                "average": round(self.average_words, 2),
            },
            "quality_flags": {
                "tiny_chunks": self.tiny_chunks,
                "oversized_chunks": self.oversized_chunks,
                "empty_chunks": self.empty_chunks,
                "missing_source_url": self.missing_source_url,
                "missing_section_path": self.missing_section_path,
                "unbalanced_code_fences": self.unbalanced_code_fences,
                "shortcode_remnants": self.shortcode_remnants,
                "duplicate_contents": self.duplicate_contents,
            },
            "examples": [example.to_dict() for example in self.examples],
        }


def audit_chunks(
    rows: Iterable[dict[str, Any]],
    *,
    min_words: int = 20,
    max_words: int = 600,
    max_examples: int = 10,
) -> ChunkAuditReport:
    """Inspect processed RAG chunks and return a compact quality report."""

    materialized = list(rows)
    report = ChunkAuditReport(total_chunks=len(materialized))
    if not materialized:
        return report

    document_ids: set[str] = set()
    word_counts: list[int] = []
    content_hashes: Counter[str] = Counter()

    for row in materialized:
        chunk_id = str(row.get("chunk_id") or "<missing-chunk-id>")
        document_id = str(row.get("document_id") or "")
        content = str(row.get("content") or "")
        source_url = str(row.get("source_url") or "")
        section_path = row.get("section_path")

        if document_id:
            document_ids.add(document_id)

        words = len(content.split())
        word_counts.append(words)

        if not content.strip():
            report.empty_chunks += 1
            _add_example(report, chunk_id, "empty chunk", content, max_examples)
        elif words < min_words:
            report.tiny_chunks += 1
            _add_example(report, chunk_id, f"tiny chunk ({words} words)", content, max_examples)

        if words > max_words:
            report.oversized_chunks += 1
            _add_example(
                report,
                chunk_id,
                f"oversized chunk ({words} words)",
                content,
                max_examples,
            )

        if not source_url:
            report.missing_source_url += 1
            _add_example(report, chunk_id, "missing source_url", content, max_examples)

        if not isinstance(section_path, list) or not section_path:
            report.missing_section_path += 1
            _add_example(report, chunk_id, "missing section_path", content, max_examples)

        if not _code_fences_balanced(content):
            report.unbalanced_code_fences += 1
            _add_example(report, chunk_id, "unbalanced fenced code block", content, max_examples)

        if _contains_shortcode_outside_fences(content):
            report.shortcode_remnants += 1
            _add_example(report, chunk_id, "shortcode remnant", content, max_examples)

        normalized = " ".join(content.split())
        if normalized:
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
            content_hashes[digest] += 1

    report.unique_documents = len(document_ids)
    report.min_words = min(word_counts)
    report.p50_words = _percentile(word_counts, 0.50)
    report.p90_words = _percentile(word_counts, 0.90)
    report.p95_words = _percentile(word_counts, 0.95)
    report.max_words = max(word_counts)
    report.average_words = mean(word_counts)
    report.duplicate_contents = sum(count - 1 for count in content_hashes.values() if count > 1)

    return report


def _add_example(
    report: ChunkAuditReport,
    chunk_id: str,
    reason: str,
    content: str,
    max_examples: int,
) -> None:
    if len(report.examples) >= max_examples:
        return

    category = _reason_category(reason)
    category_count = sum(_reason_category(item.reason) == category for item in report.examples)
    if category_count >= 2:
        return

    preview = " ".join(content.split())[:240]
    report.examples.append(AuditExample(chunk_id=chunk_id, reason=reason, preview=preview))


def _reason_category(reason: str) -> str:
    if reason.startswith("tiny chunk"):
        return "tiny chunk"
    if reason.startswith("oversized chunk"):
        return "oversized chunk"
    return reason


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0

    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _code_fences_balanced(content: str) -> bool:
    """Return whether Markdown fenced code blocks open and close correctly."""

    open_marker: str | None = None

    for line in content.splitlines():
        match = _FENCE_RE.match(line)
        if match is None:
            continue

        marker = match.group(1)
        rest = match.group(2)

        if open_marker is None:
            open_marker = marker
            continue

        if _is_closing_fence(marker, rest, open_marker):
            open_marker = None

    return open_marker is None


def _contains_shortcode_outside_fences(content: str) -> bool:
    """Return True only for Docker/Hugo shortcodes that leaked into prose."""

    open_marker: str | None = None

    for line in content.splitlines():
        match = _FENCE_RE.match(line)
        if match is not None:
            marker = match.group(1)
            rest = match.group(2)
            if open_marker is None:
                open_marker = marker
            elif _is_closing_fence(marker, rest, open_marker):
                open_marker = None
            continue

        if open_marker is None and _SHORTCODE_TOKEN_RE.search(line):
            return True

    return False


def _is_closing_fence(marker: str, rest: str, open_marker: str) -> bool:
    return (
        marker[0] == open_marker[0]
        and len(marker) >= len(open_marker)
        and not rest.strip()
    )
