from __future__ import annotations

import argparse

from docker_agent.config import get_settings
from docker_agent.db import create_db_engine
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.store import (
    HybridSearchResult,
    KeywordSearchResult,
    SearchResult,
    search_hybrid_chunks,
    search_keyword_chunks,
    search_similar_chunks,
)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Search Docker Docs with dense, keyword, or hybrid retrieval."
    )
    parser.add_argument("query", help="Natural-language search query, Chinese or English")
    parser.add_argument("--top-k", type=int, default=settings.retrieval_top_k)
    parser.add_argument(
        "--mode",
        choices=("dense", "keyword", "hybrid"),
        default="dense",
    )
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise SystemExit("--top-k must be positive")
    if args.candidate_k < args.top_k:
        raise SystemExit("--candidate-k must be greater than or equal to --top-k")

    engine = create_db_engine()
    if args.mode == "keyword":
        results = search_keyword_chunks(engine, args.query, top_k=args.top_k)
    else:
        embedder = BgeM3Embedder()
        query_embedding = embedder.embed_query(args.query)
        if args.mode == "dense":
            results = search_similar_chunks(engine, query_embedding, top_k=args.top_k)
        else:
            results = search_hybrid_chunks(
                engine,
                args.query,
                query_embedding,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )

    if not results:
        print("No matching chunks found. Make sure the corpus is indexed first.")
        return

    for index, result in enumerate(results, start=1):
        section = " > ".join(result.section_path)
        preview = " ".join(result.content.split())[:500]
        print(f"\n[{index}] {_score_label(result)}")
        print(f"Title:   {result.title}")
        print(f"Section: {section}")
        print(f"Source:  {result.source_url}")
        print(f"Preview: {preview}")


def _score_label(result: SearchResult | KeywordSearchResult | HybridSearchResult) -> str:
    if isinstance(result, SearchResult):
        return f"dense_score={result.score:.4f} distance={result.distance:.4f}"
    if isinstance(result, KeywordSearchResult):
        return f"keyword_score={result.rank_score:.4f}"

    dense_rank = result.dense_rank if result.dense_rank is not None else "-"
    keyword_rank = result.keyword_rank if result.keyword_rank is not None else "-"
    return (
        f"rrf_score={result.rrf_score:.6f} "
        f"dense_rank={dense_rank} keyword_rank={keyword_rank}"
    )


if __name__ == "__main__":
    main()
