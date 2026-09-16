from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_STANDALONE_SHORTCODE_RE = re.compile(r"^\s*\{\{[%<].*[>%]\}\}\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(slots=True)
class MarkdownSection:
    section_path: list[str]
    content: str


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Return YAML front matter and the Markdown body.

    Docker Docs pages commonly start with a YAML block delimited by `---`.
    Pages without front matter are returned unchanged.
    """

    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break

    if closing_index is None:
        return {}, text

    raw_front_matter = "\n".join(lines[1:closing_index])
    metadata = yaml.safe_load(raw_front_matter) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    body = "\n".join(lines[closing_index + 1 :]).lstrip("\n")
    return metadata, body


def clean_markdown(body: str) -> str:
    """Remove presentation-only shortcode lines while preserving technical text.

    The cleaner intentionally keeps commands, fenced code blocks, error strings,
    lists, and prose because they are valuable retrieval evidence.
    """

    cleaned: list[str] = []
    in_fence = False
    fence_marker: str | None = None

    for line in body.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            cleaned.append(line.rstrip())
            continue

        if not in_fence and _STANDALONE_SHORTCODE_RE.match(line):
            continue

        cleaned.append(line.rstrip())

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def first_h1(body: str) -> str | None:
    """Return the first level-one heading outside fenced code blocks."""

    in_fence = False
    fence_marker: str | None = None

    for line in body.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue

        if not in_fence:
            match = _HEADING_RE.match(line)
            if match and len(match.group(1)) == 1:
                return _clean_heading(match.group(2))

    return None


def split_sections(body: str, fallback_title: str) -> list[MarkdownSection]:
    """Split Markdown by headings without treating headings inside code as structure."""

    sections: list[MarkdownSection] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_path: list[str] = [fallback_title]
    in_fence = False
    fence_marker: str | None = None

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(MarkdownSection(section_path=current_path.copy(), content=content))
        current_lines.clear()

    for line in body.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            current_lines.append(line)
            continue

        heading_match = None if in_fence else _HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            heading = _clean_heading(heading_match.group(2))

            heading_stack[:] = heading_stack[: level - 1]
            while len(heading_stack) < level - 1:
                heading_stack.append(fallback_title)
            heading_stack.append(heading)
            current_path = heading_stack.copy()
            continue

        current_lines.append(line)

    flush()
    return sections


def split_section_content(
    content: str,
    *,
    max_words: int = 450,
    overlap_words: int = 60,
) -> list[str]:
    """Split a long section into paragraph/code-block groups.

    Fenced code blocks are kept atomic. Text chunks receive a small word overlap so
    adjacent retrieval units do not lose context at their boundary.
    """

    if _word_count(content) <= max_words:
        return [content.strip()] if content.strip() else []

    blocks = _markdown_blocks(content)
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for block in blocks:
        block_words = _word_count(block)

        if current and current_words + block_words > max_words:
            chunk = "\n\n".join(current).strip()
            chunks.append(chunk)

            overlap = " ".join(chunk.split()[-overlap_words:]) if overlap_words else ""
            current = [overlap] if overlap else []
            current_words = _word_count(overlap)

        if block_words > max_words and not _is_fenced_block(block):
            words = block.split()
            start = 0
            while start < len(words):
                piece = " ".join(words[start : start + max_words])
                if current:
                    piece = "\n\n".join([*current, piece])
                    current = []
                    current_words = 0
                chunks.append(piece.strip())
                start += max_words - overlap_words
            continue

        current.append(block)
        current_words += block_words

    if current:
        chunks.append("\n\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def source_url_from_path(file_path: str) -> str:
    """Map a Docker Docs repository path to its docs.docker.com page."""

    path = Path(file_path).as_posix()
    if path.startswith("content/manuals/"):
        path = path.removeprefix("content/manuals/")
    elif path.startswith("content/"):
        path = path.removeprefix("content/")

    if path.endswith("/_index.md"):
        path = path[: -len("_index.md")]
    elif path.endswith(".md"):
        path = path[:-3]

    return f"https://docs.docker.com/{path.strip('/')}/"


def _markdown_blocks(content: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    fence_marker: str | None = None

    def flush() -> None:
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
        current.clear()

    for line in content.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                flush()
                in_fence = True
                fence_marker = marker
            current.append(line)
            if in_fence and len(current) > 1 and marker == fence_marker:
                in_fence = False
                fence_marker = None
                flush()
            continue

        if in_fence:
            current.append(line)
            continue

        if not line.strip():
            flush()
            continue

        current.append(line)

    flush()
    return blocks


def _is_fenced_block(block: str) -> bool:
    stripped = block.lstrip()
    return stripped.startswith(("```", "~~~"))


def _word_count(text: str) -> int:
    return len(text.split())


def _clean_heading(value: str) -> str:
    value = re.sub(r"\s+#+\s*$", "", value).strip()
    return value
