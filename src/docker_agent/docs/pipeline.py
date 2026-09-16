from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from docker_agent.docs.markdown import (
    clean_markdown,
    first_h1,
    parse_front_matter,
    source_url_from_path,
    split_section_content,
    split_sections,
)
from docker_agent.docs.models import Chunk, Document

DEFAULT_INCLUDE_PREFIXES = (
    "content/get-started",
    "content/manuals/engine",
    "content/manuals/compose",
)


def select_markdown_files(
    raw_repo: Path,
    selected_root: Path,
    prefixes: tuple[str, ...] = DEFAULT_INCLUDE_PREFIXES,
) -> list[Path]:
    """Copy the selected Docker Docs Markdown files into a smaller working set."""

    if not raw_repo.exists():
        raise FileNotFoundError(f"Docker Docs repository not found: {raw_repo}")

    if selected_root.exists():
        shutil.rmtree(selected_root)
    selected_root.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for prefix in prefixes:
        source_dir = raw_repo / prefix
        if not source_dir.exists():
            continue

        for source_path in sorted(source_dir.rglob("*.md")):
            relative = source_path.relative_to(raw_repo)
            target = selected_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            copied.append(target)

    return copied


def build_dataset(
    selected_root: Path,
    output_dir: Path,
    *,
    max_words: int = 450,
    overlap_words: int = 60,
) -> tuple[list[Document], list[Chunk]]:
    """Build cleaned documents and retrieval chunks from selected Markdown files."""

    documents: list[Document] = []
    chunks: list[Chunk] = []

    markdown_files = sorted(selected_root.rglob("*.md"))
    if not markdown_files:
        raise FileNotFoundError(f"No Markdown files found under {selected_root}")

    for markdown_file in markdown_files:
        relative_path = markdown_file.relative_to(selected_root).as_posix()
        raw_text = markdown_file.read_text(encoding="utf-8")
        metadata, body = parse_front_matter(raw_text)
        cleaned_body = clean_markdown(body)

        if not cleaned_body:
            continue

        title = str(metadata.get("title") or first_h1(cleaned_body) or markdown_file.stem)
        document_id = _stable_id("document", relative_path)
        source_url = source_url_from_path(relative_path)

        document = Document(
            document_id=document_id,
            source="docker_docs",
            file_path=relative_path,
            title=title,
            source_url=source_url,
            language="en",
            content=cleaned_body,
        )
        documents.append(document)

        chunk_index = 0
        for section in split_sections(cleaned_body, fallback_title=title):
            for piece in split_section_content(
                section.content,
                max_words=max_words,
                overlap_words=overlap_words,
            ):
                chunk_index += 1
                chunks.append(
                    Chunk(
                        chunk_id=f"{document_id}__{chunk_index:04d}",
                        document_id=document_id,
                        title=title,
                        section_path=section.section_path,
                        content=piece,
                        source_url=source_url,
                        file_path=relative_path,
                        word_count=len(piece.split()),
                    )
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "documents.jsonl", [doc.to_dict() for doc in documents])
    _write_jsonl(output_dir / "chunks.jsonl", [chunk.to_dict() for chunk in chunks])

    return documents, chunks


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"docker_{kind}_{digest}"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
