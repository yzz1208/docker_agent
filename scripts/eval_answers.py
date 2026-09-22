from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from docker_agent.config import get_settings
from docker_agent.db import check_database, create_db_engine
from docker_agent.rag.answer import CitationValidationError, generate_grounded_answer
from docker_agent.rag.answer_evaluation import (
    AnswerEvalCase,
    evaluate_answer_deterministically,
    judge_answer,
    summarize_deterministic_metrics,
    summarize_judge_results,
)
from docker_agent.rag.context import build_rag_context
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.llm import OpenAICompatibleChatClient
from docker_agent.rag.reranker import BgeReranker, rerank_candidates
from docker_agent.rag.store import (
    reciprocal_rank_fusion,
    search_keyword_chunks,
    search_similar_chunks,
)

DEFAULT_INPUT = Path("data/eval/answer_v1.jsonl")
DEFAULT_OUTPUT = Path("reports/answer_eval_latest.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate grounded Docker RAG answers on the answer_v1 dataset."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run an additional LLM-as-judge rubric pass for each generated answer.",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[AnswerEvalCase]:
    cases: list[AnswerEvalCase] = []
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
            question = str(row.get("question") or "").strip()
            answerable = row.get("answerable")
            expected_paths = row.get("expected_file_paths", [])
            concept_groups = row.get("required_concept_groups", [])

            if not case_id or not question:
                raise ValueError(f"Case at {path}:{line_number} requires id and question")
            if not isinstance(answerable, bool):
                raise TypeError(f"Case {case_id} answerable must be boolean")
            if not isinstance(expected_paths, list):
                raise TypeError(f"Case {case_id} expected_file_paths must be a list")
            if not isinstance(concept_groups, list):
                raise TypeError(f"Case {case_id} required_concept_groups must be a list")
            if answerable and not expected_paths:
                raise ValueError(
                    f"Answerable case {case_id} requires at least one expected_file_path"
                )

            normalized_groups: list[tuple[str, ...]] = []
            for group in concept_groups:
                if not isinstance(group, list) or not group:
                    raise TypeError(
                        f"Case {case_id} concept groups must be non-empty lists"
                    )
                normalized_groups.append(
                    tuple(str(item).strip() for item in group if str(item).strip())
                )

            cases.append(
                AnswerEvalCase(
                    case_id=case_id,
                    question=question,
                    answerable=answerable,
                    expected_file_paths=frozenset(
                        str(item) for item in expected_paths if str(item).strip()
                    ),
                    required_concept_groups=tuple(normalized_groups),
                )
            )
    return cases


def _release_cuda_cache() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _model_client(*, temperature: float) -> OpenAICompatibleChatClient:
    settings = get_settings()
    return OpenAICompatibleChatClient(
        model=settings.model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
        temperature=temperature,
    )


def _validate_environment() -> None:
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("MODEL_NAME", settings.model_name),
            ("MODEL_BASE_URL", settings.model_base_url),
        )
        if not value.strip()
    ]
    if missing:
        raise SystemExit(
            "Missing model configuration: "
            + ", ".join(missing)
            + ". Configure .env before running eval_answers.py."
        )


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Answer evaluation file not found: {args.input}")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    _validate_environment()
    settings = get_settings()
    cases = load_cases(args.input)
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("Answer evaluation file contains no cases")

    engine = create_db_engine()
    try:
        check_database(engine)
    except SQLAlchemyError:
        raise SystemExit(
            "PostgreSQL is unavailable. Start Docker Desktop and run "
            "docker compose up -d postgres, then retry."
        ) from None

    embedder = BgeM3Embedder()
    vectors = embedder.embed_documents(
        [case.question for case in cases],
        show_progress_bar=False,
    )
    del embedder
    _release_cuda_cache()

    reranker = BgeReranker()
    # Use deterministic decoding for repeatable evaluation runs.
    answer_model = _model_client(temperature=0.0)
    judge_model = _model_client(temperature=0.0) if args.judge else None

    deterministic_metrics = []
    judge_results = []
    output_rows: list[dict[str, Any]] = []
    failures = 0

    for index, case in enumerate(cases):
        vector = vectors[index]
        dense = search_similar_chunks(
            engine,
            vector,
            top_k=settings.retrieval_candidate_k,
        )
        keyword = search_keyword_chunks(
            engine,
            case.question,
            top_k=settings.retrieval_candidate_k,
        )
        rrf = reciprocal_rank_fusion(
            dense,
            keyword,
            top_k=settings.retrieval_candidate_k,
            rrf_k=settings.retrieval_rrf_k,
            dense_weight=settings.retrieval_dense_weight,
            keyword_weight=settings.retrieval_keyword_weight,
        )
        reranked = rerank_candidates(
            case.question,
            rrf,
            reranker,
            top_k=settings.rerank_top_k,
        )
        context = build_rag_context(
            reranked,
            max_sources=settings.rerank_top_k,
            max_chars=settings.rag_context_max_chars,
        )

        try:
            result = generate_grounded_answer(case.question, context, answer_model)
        except CitationValidationError as exc:
            failures += 1
            row = {
                "id": case.case_id,
                "question": case.question,
                "generation_error": str(exc),
            }
            output_rows.append(row)
            print(f"[{case.case_id}] FAIL invalid_citation={exc}")
            continue

        metrics = evaluate_answer_deterministically(case, result)
        deterministic_metrics.append(metrics)

        row = {
            "id": case.case_id,
            "question": case.question,
            "answerable": case.answerable,
            "answer": result.answer,
            "citation_indices": list(result.citation_indices),
            "cited_sources": [
                {
                    "index": source.index,
                    "title": source.title,
                    "file_path": source.file_path,
                    "source_url": source.source_url,
                }
                for source in result.cited_sources
            ],
            "retrieved_sources": [
                {
                    "index": source.index,
                    "title": source.title,
                    "file_path": source.file_path,
                    "source_url": source.source_url,
                }
                for source in result.sources
            ],
            "deterministic": {
                "citations_present": metrics.citations_present,
                "cited_source_count": metrics.cited_source_count,
                "retrieved_expected_source_hit": metrics.retrieved_expected_source_hit,
                "cited_expected_source_hit": metrics.cited_expected_source_hit,
                "expected_source_recall": metrics.expected_source_recall,
                "concept_coverage": metrics.concept_coverage,
            },
        }

        judge_label = ""
        if judge_model is not None:
            judged = judge_answer(case, result, context, judge_model)
            judge_results.append(judged)
            row["judge"] = {
                "groundedness": judged.groundedness,
                "citation_correctness": judged.citation_correctness,
                "completeness": judged.completeness,
                "insufficient_evidence_handling": judged.insufficient_evidence_handling,
                "unsupported_claims": list(judged.unsupported_claims),
                "rationale": judged.rationale,
            }
            judge_label = (
                f" grounded={judged.groundedness}/5"
                f" citation={judged.citation_correctness}/5"
                f" complete={judged.completeness}/5"
            )

        output_rows.append(row)
        print(
            f"[{case.case_id}] citations={len(result.citation_indices)} "
            f"source_hit={metrics.cited_expected_source_hit} "
            f"concepts={metrics.concept_coverage:.2f}{judge_label}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "cases": len(cases),
        "generation_failures": failures,
        "deterministic": summarize_deterministic_metrics(deterministic_metrics),
        "answer_temperature": 0.0,
        "output": str(args.output),
    }
    if judge_model is not None:
        summary["judge"] = summarize_judge_results(judge_results)
        summary["judge_note"] = (
            "LLM-assisted scores are diagnostic, not gold labels. "
            "A separate judge model can be added later."
        )

    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
