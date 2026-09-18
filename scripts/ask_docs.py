from __future__ import annotations

import argparse
import gc

from sqlalchemy.exc import SQLAlchemyError

from docker_agent.config import get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.rag.answer import generate_grounded_answer
from docker_agent.rag.context import build_rag_context
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.llm import OpenAICompatibleChatClient
from docker_agent.rag.reranker import BgeReranker, rerank_candidates
from docker_agent.rag.store import (
    reciprocal_rank_fusion,
    search_keyword_chunks,
    search_similar_chunks,
)


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Answer a Docker question using reranked official Docker Docs context."
    )
    parser.add_argument("question", help="Docker support question, Chinese or English")
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=settings.retrieval_candidate_k,
        help="Dense/keyword depth and RRF pool size before reranking.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.rerank_top_k,
        help="Number of reranked chunks available to the context builder.",
    )
    parser.add_argument(
        "--context-max-chars",
        type=int,
        default=settings.rag_context_max_chars,
    )
    return parser.parse_args()


def _release_cuda_cache() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _validate_model_settings() -> None:
    settings = get_settings()
    missing: list[str] = []
    if not settings.model_name.strip():
        missing.append("MODEL_NAME")
    if not settings.model_base_url.strip():
        missing.append("MODEL_BASE_URL")
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"Missing model configuration: {joined}. Configure .env before running ask_docs.py."
        )


def main() -> None:
    args = parse_args()
    if not args.question.strip():
        raise SystemExit("question must not be empty")
    if args.candidate_k <= 0 or args.top_k <= 0:
        raise SystemExit("candidate/top-k values must be positive")
    if args.candidate_k < args.top_k:
        raise SystemExit("--candidate-k must be greater than or equal to --top-k")
    if args.context_max_chars <= 0:
        raise SystemExit("--context-max-chars must be positive")

    _validate_model_settings()
    settings = get_settings()

    engine = create_db_engine()
    try:
        check_database(engine)
    except SQLAlchemyError:
        raise SystemExit(
            "PostgreSQL is unavailable. Start Docker Desktop and run "
            "docker compose up -d postgres, then retry."
        ) from None

    embedder = BgeM3Embedder()
    query_embedding = embedder.embed_query(args.question)
    dense_candidates = search_similar_chunks(
        engine,
        query_embedding,
        top_k=args.candidate_k,
    )
    keyword_candidates = search_keyword_chunks(
        engine,
        args.question,
        top_k=args.candidate_k,
    )
    rrf_candidates = reciprocal_rank_fusion(
        dense_candidates,
        keyword_candidates,
        top_k=args.candidate_k,
        rrf_k=settings.retrieval_rrf_k,
        dense_weight=settings.retrieval_dense_weight,
        keyword_weight=settings.retrieval_keyword_weight,
    )

    del embedder
    _release_cuda_cache()

    reranker = BgeReranker()
    reranked = rerank_candidates(
        args.question,
        rrf_candidates,
        reranker,
        top_k=args.top_k,
    )
    if not reranked:
        raise SystemExit("No Docker documentation chunks were retrieved.")

    context = build_rag_context(
        reranked,
        max_sources=args.top_k,
        max_chars=args.context_max_chars,
    )

    model = OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=settings.model_temperature,
    )
    result = generate_grounded_answer(args.question, context, model)

    print("\nAnswer\n")
    print(result.answer)
    print("\nSources")
    for source in result.sources:
        section = f" > {source.section}" if source.section else ""
        print(f"[{source.index}] {source.title}{section}")
        print(f"    {source.source_url}")

    if result.context_truncated:
        print("\nNote: retrieved context was truncated to the configured character budget.")


if __name__ == "__main__":
    main()
