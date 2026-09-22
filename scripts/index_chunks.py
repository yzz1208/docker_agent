from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.db import create_db_engine
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.store import clear_chunks, init_vector_store, upsert_chunk_batch
from docker_agent.rag.text import build_embedding_text

DEFAULT_INPUT = Path("data/processed/chunks.jsonl")


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected a JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed Docker Docs chunks into pgvector.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(
            f"Chunk file not found: {args.input}. Run scripts/build_docs.py first."
        )
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    rows = load_rows(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]

    init_vector_store()
    engine = create_db_engine()
    if args.reset:
        clear_chunks(engine)

    embedder = BgeM3Embedder()
    total = len(rows)
    indexed = 0

    for start in range(0, total, args.batch_size):
        batch = rows[start : start + args.batch_size]
        texts: list[str] = []
        for row in batch:
            section_path = row.get("section_path")
            if not isinstance(section_path, list):
                raise TypeError(f"Invalid section_path for chunk {row.get('chunk_id')}")
            texts.append(
                build_embedding_text(
                    title=str(row.get("title") or ""),
                    section_path=[str(part) for part in section_path],
                    content=str(row.get("content") or ""),
                )
            )

        embeddings = embedder.embed_documents(texts, show_progress_bar=False)
        indexed += upsert_chunk_batch(engine, batch, embeddings)
        print(f"Indexed {indexed}/{total} chunks")

    print(f"Done. Indexed {indexed} chunks into PostgreSQL/pgvector.")


if __name__ == "__main__":
    main()
