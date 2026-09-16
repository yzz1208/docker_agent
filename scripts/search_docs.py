from __future__ import annotations

import argparse

from docker_agent.config import get_settings
from docker_agent.db import create_db_engine
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.store import search_similar_chunks


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Search Docker Docs with BGE-M3 + pgvector.")
    parser.add_argument("query", help="Natural-language search query, Chinese or English")
    parser.add_argument("--top-k", type=int, default=settings.retrieval_top_k)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise SystemExit("--top-k must be positive")

    embedder = BgeM3Embedder()
    query_embedding = embedder.embed_query(args.query)
    engine = create_db_engine()
    results = search_similar_chunks(engine, query_embedding, top_k=args.top_k)

    if not results:
        print("No indexed chunks found. Run scripts/index_chunks.py first.")
        return

    for index, result in enumerate(results, start=1):
        section = " > ".join(result.section_path)
        preview = " ".join(result.content.split())[:500]
        print(f"\n[{index}] score={result.score:.4f} distance={result.distance:.4f}")
        print(f"Title:   {result.title}")
        print(f"Section: {section}")
        print(f"Source:  {result.source_url}")
        print(f"Preview: {preview}")


if __name__ == "__main__":
    main()
