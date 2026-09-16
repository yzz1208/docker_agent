from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SHORTCODE_TOKEN_RE = re.compile(r"\{\{[%<].*?[>%]\}\}")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_LOW_VALUE_PREFIXES = (
    "now that ",
    "the following links provide",
    "for more information, see",
    "for more information see",
    "to learn more, see",
    "to learn more see",
)


@dataclass(slots=True)
class MarkdownSection:
    section_path: list[str]
    content: str


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Return YAML front matter and the Markdown body."""

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
    """Remove presentation-only shortcodes while preserving technical content.

    Shortcode tokens are removed only outside fenced code blocks. This keeps literal
    examples intact while stripping Docker Docs/Hugo rendering syntax from prose.
    """

    cleaned: list[str] = []
    open_fence: str | None = None

    for original_line in body.splitlines():
        fence = _fence_parts(original_line)
        if fence is not None:
            marker, rest = fence
            if open_fence is None:
                open_fence = marker
            elif _is_closing_fence(marker, rest, open_fence):
                open_fence = None
            cleaned.append(original_line.rstrip())
            continue

        line = original_line
        if open_fence is None:
            line = _SHORTCODE_TOKEN_RE.sub("", line)

        cleaned.append(line.rstrip())

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def first_h1(body: str) -> str | None:
    """Return the first level-one heading outside fenced code blocks."""

    open_fence: str | None = None

    for line in body.splitlines():
        fence = _fence_parts(line)
        if fence is not None:
            marker, rest = fence
            if open_fence is None:
                open_fence = marker
            elif _is_closing_fence(marker, rest, open_fence):
                open_fence = None
            continue

        if open_fence is None:
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
    open_fence: str | None = None

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(MarkdownSection(section_path=current_path.copy(), content=content))
        current_lines.clear()

    for line in body.splitlines():
        fence = _fence_parts(line)
        if fence is not None:
            marker, rest = fence
            if open_fence is None:
                open_fence = marker
            elif _is_closing_fence(marker, rest, open_fence):
                open_fence = None
            current_lines.append(line)
            continue

        heading_match = None if open_fence is not None else _HEADING_RE.match(line)
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

    Fenced code blocks are kept atomic. Chunk overlap is copied only from prose so
    Markdown fence markers cannot be detached from their matching code block.
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

            overlap = _safe_overlap_text(chunk, overlap_words)
            current = [overlap] if overlap else []
            current_words = _word_count(overlap)

        if block_words > max_words and not _is_fenced_block(block):
            words = block.split()
            start = 0
            step = max_words - overlap_words
            while start < len(words):
                piece = " ".join(words[start : start + max_words])
                if current:
                    piece = "\n\n".join([*current, piece])
                    current = []
                    current_words = 0
                chunks.append(piece.strip())
                start += step
            continue

        current.append(block)
        current_words += block_words

    if current:
        chunks.append("\n\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def is_low_value_chunk(content: str, *, max_words: int = 24) -> bool:
    """Return True for tiny navigation/transition fragments with little RAG value.

    We intentionally do not remove every short chunk. Concise definitions, commands,
    warnings, and error messages can be highly useful. The filter only targets obvious
    link lists and transition prose seen in Docker's tutorial navigation sections.
    """

    stripped = content.strip()
    if not stripped:
        return True

    words = len(stripped.split())
    if words > max_words or _is_fenced_block(stripped):
        return False

    links = _MARKDOWN_LINK_RE.findall(stripped)
    if len(links) >= 2:
        residual = _MARKDOWN_LINK_RE.sub("", stripped)
        residual_words = len(residual.replace("*", " ").replace("-", " ").split())
        if residual_words <= 8:
            return True

    normalized = " ".join(stripped.lower().split())
    return normalized.startswith(_LOW_VALUE_PREFIXES)


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
    open_fence: str | None = None

    def flush() -> None:
        block = "\n".join(current).strip()
        if block:
            blocks.append(block)
        current.clear()

    for line in content.splitlines():
        fence = _fence_parts(line)

        if open_fence is not None:
            current.append(line)
            if fence is not None:
                marker, rest = fence
                if _is_closing_fence(marker, rest, open_fence):
                    open_fence = None
                    flush()
            continue

        if fence is not None:
            flush()
            marker, _ = fence
            open_fence = marker
            current.append(line)
            continue

        if not line.strip():
            flush()
            continue

        current.append(line)

    flush()
    return blocks


def _safe_overlap_text(chunk: str, overlap_words: int) -> str:
    """Return prose-only overlap without fenced code content or fence markers."""

    if overlap_words <= 0:
        return ""

    prose_lines: list[str] = []
    open_fence: str | None = None

    for line in chunk.splitlines():
        fence = _fence_parts(line)
        if fence is not None:
            marker, rest = fence
            if open_fence is None:
                open_fence = marker
            elif _is_closing_fence(marker, rest, open_fence):
                open_fence = None
            continue

        if open_fence is None:
            prose_lines.append(line)

    words = " ".join(prose_lines).split()
    return " ".join(words[-overlap_words:])


def _fence_parts(line: str) -> tuple[str, str] | None:
    match = _FENCE_RE.match(line)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _is_closing_fence(marker: str, rest: str, open_fence: str) -> bool:
    return marker[0] == open_fence[0] and len(marker) >= len(open_fence) and not rest.strip()


def _is_fenced_block(block: str) -> bool:
    return block.lstrip().startswith(("```", "~~~"))


def _word_count(text: str) -> int:
    return len(text.split())


def _clean_heading(value: str) -> str:
    value = re.sub(r"\s+#+\s*$", "", value).strip()
    return value
