from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Any

from docker_agent.db import create_db_engine
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.evaluation import (
    RetrievalCase,
    evaluate_candidate_coverage,
    evaluate_case,
    summarize_candidate_coverage,
    summarize_metrics,
    validate_case_labels,
)
from docker_agent.rag.reranker import BgeReranker, rerank_candidates
from docker_agent.rag.store import (
    reciprocal_rank_fusion,
    search_keyword_chunks,
    search_similar_chunks,
)

DEFAULT_INPUT = Path("data/eval/retrieval_v2.jsonl")
DEFAULT_CHUNKS = Path("data/processed/chunks.jsonl")
K_VALUES = (1, 3, 5)
CANDIDATE_K_VALUES = (10, 20)


def load_cases(path: Path) -> list[RetrievalCase]:
    cases: list[RetrievalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected a JSON object at {path}:{line_number}")

            case_id = str(row.get("id") or "").strip()
            query = str(row.get("query") or "").strip()
            relevant = row.get("relevant_file_paths")
            section_terms = row.get("relevant_section_terms", [])

            if not case_id or not query:
                raise ValueError(f"Case at {path}:{line_number} requires id and query")
            if not isinstance(relevant, list) or not relevant:
                raise ValueError(
                    f"Case {case_id} at {path}:{line_number} requires relevant_file_paths"
                )
            if not isinstance(section_terms, list):
                raise TypeError(
                    f"Case {case_id} at {path}:{line_number} relevant_section_terms must be a list"
                )

            cases.append(
                RetrievalCase(
                    case_id=case_id,
                    query=query,
                    relevant_file_paths=frozenset(str(item) for item in relevant),
                    relevant_section_terms=tuple(
                        str(item).strip() for item in section_terms if str(item).strip()
                    ),
                )
            )
    return cases


def load_chunk_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"Expected a JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate dense, keyword, hybrid, or reranked retrieval on Docker Docs."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--top-k", type=int, default=max(K_VALUES))
    parser.add_argument(
        "--mode",
        choices=("dense", "keyword", "hybrid", "rerank"),
        default="dense",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=20,
        help="Candidate depth per retriever before RRF/reranking.",
    )
    parser.add_argument(
        "--rrf-k",
        type=int,
        default=60,
        help="RRF rank constant. Higher values make rank differences less aggressive.",
    )
    parser.add_argument(
        "--dense-weight",
        type=float,
        default=1.0,
        help="Dense contribution weight for hybrid RRF.",
    )
    parser.add_argument(
        "--keyword-weight",
        type=float,
        default=1.0,
        help="Keyword contribution weight for hybrid RRF.",
    )
    parser.add_argument(
        "--skip-label-validation",
        action="store_true",
        help="Skip checking eval file/section labels against processed chunks.",
    )
    return parser.parse_args()


def _release_embedding_model(embedder: BgeM3Embedder) -> None:
    """Release the embedding model before loading the reranker on small GPUs."""

    del embedder
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Evaluation file not found: {args.input}")
    if args.top_k < max(K_VALUES):
        raise SystemExit(f"--top-k must be at least {max(K_VALUES)}")
    if args.mode in {"hybrid", "rerank"} and args.candidate_k < max(CANDIDATE_K_VALUES):
        raise SystemExit(
            f"{args.mode} evaluation requires --candidate-k >= {max(CANDIDATE_K_VALUES)} "
            "for candidate coverage metrics"
        )
    if args.dense_weight < 0 or args.keyword_weight < 0:
        raise SystemExit("RRF weights must be non-negative")
    if args.dense_weight == 0 and args.keyword_weight == 0:
        raise SystemExit("At least one RRF weight must be positive")

    cases = load_cases(args.input)
    if not cases:
        raise SystemExit("Evaluation file contains no cases")

    if not args.skip_label_validation:
        if not args.chunks.exists():
            raise SystemExit(
                f"Chunk file not found: {args.chunks}. Run scripts/build_docs.py first."
            )
        validate_case_labels(cases, load_chunk_rows(args.chunks))
        print(f"Validated {len(cases)} evaluation cases against {args.chunks}.")

    vectors: list[list[float]] | None = None
    if args.mode in {"dense", "hybrid", "rerank"}:
        embedder = BgeM3Embedder()
        vectors = embedder.embed_documents(
            [case.query for case in cases],
            show_progress_bar=False,
        )
        if args.mode == "rerank":
            _release_embedding_model(embedder)

    reranker = BgeReranker() if args.mode == "rerank" else None
    engine = create_db_engine()
    case_metrics = []
    candidate_metrics = []

    for index, case in enumerate(cases):
        candidate_label = ""

        if args.mode == "keyword":
            results = search_keyword_chunks(engine, case.query, top_k=args.top_k)
        else:
            assert vectors is not None
            vector = vectors[index]
            if args.mode == "dense":
                results = search_similar_chunks(engine, vector, top_k=args.top_k)
            else:
                dense_candidates = search_similar_chunks(
                    engine,
                    vector,
                    top_k=args.candidate_k,
                )
                keyword_candidates = search_keyword_chunks(
                    engine,
                    case.query,
                    top_k=args.candidate_k,
                )
                coverage = evaluate_candidate_coverage(
                    case,
                    dense_candidates,
                    keyword_candidates,
                    k_values=CANDIDATE_K_VALUES,
                )
                candidate_metrics.append(coverage)
                candidate_label = (
                    f" candidate_union@20="
                    f"{'HIT' if coverage.union_hit_at[20] else 'MISS'}"
                )

                if args.mode == "hybrid":
                    results = reciprocal_rank_fusion(
                        dense_candidates,
                        keyword_candidates,
                        top_k=args.top_k,
                        rrf_k=args.rrf_k,
                        dense_weight=args.dense_weight,
                        keyword_weight=args.keyword_weight,
                    )
                else:
                    assert reranker is not None
                    union_candidates = reciprocal_rank_fusion(
                        dense_candidates,
                        keyword_candidates,
                        top_k=args.candidate_k * 2,
                        rrf_k=args.rrf_k,
                        dense_weight=args.dense_weight,
                        keyword_weight=args.keyword_weight,
                    )
                    results = rerank_candidates(
                        case.query,
                        union_candidates,
                        reranker,
                        top_k=args.top_k,
                    )

        metrics = evaluate_case(case, results, k_values=K_VALUES)
        case_metrics.append(metrics)

        top1 = results[0] if results else None
        top1_label = top1.file_path if top1 is not None else "<no results>"
        document_rank = metrics.first_relevant_rank or "MISS"
        section_rank: int | str = "N/A"
        if metrics.has_section_labels:
            section_rank = metrics.section_first_relevant_rank or "MISS"

        print(
            f"[{case.case_id}] doc_rank={document_rank} section_rank={section_rank} "
            f"top1={top1_label}{candidate_label} query={case.query}"
        )

    summary = summarize_metrics(case_metrics, k_values=K_VALUES)
    payload: dict[str, Any] = {
        "mode": args.mode,
        "cases": summary.cases,
        "document": {
            "hit_at": {str(k): round(value, 4) for k, value in summary.hit_at.items()},
            "recall_at": {
                str(k): round(value, 4) for k, value in summary.recall_at.items()
            },
            "mrr": round(summary.mrr, 4),
        },
        "section": {
            "cases": summary.section_cases,
            "hit_at": {
                str(k): round(value, 4) for k, value in summary.section_hit_at.items()
            },
            "mrr": round(summary.section_mrr, 4),
        },
    }

    if candidate_metrics:
        candidate_summary = summarize_candidate_coverage(
            candidate_metrics,
            k_values=CANDIDATE_K_VALUES,
        )
        payload["candidate_coverage"] = {
            "candidate_k": args.candidate_k,
            "dense_hit_at": {
                str(k): round(value, 4)
                for k, value in candidate_summary.dense_hit_at.items()
            },
            "keyword_hit_at": {
                str(k): round(value, 4)
                for k, value in candidate_summary.keyword_hit_at.items()
            },
            "union_hit_at": {
                str(k): round(value, 4)
                for k, value in candidate_summary.union_hit_at.items()
            },
            "union_recall_at": {
                str(k): round(value, 4)
                for k, value in candidate_summary.union_recall_at.items()
            },
            "rrf": {
                "k": args.rrf_k,
                "dense_weight": args.dense_weight,
                "keyword_weight": args.keyword_weight,
            },
        }

    if args.mode == "rerank":
        payload["reranker"] = {
            "model": reranker.model_name if reranker is not None else None,
            "candidate_pool_max": args.candidate_k * 2,
        }

    print("\nSummary")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
