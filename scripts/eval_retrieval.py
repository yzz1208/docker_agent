from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from docker_agent.db import create_db_engine
from docker_agent.rag.embeddings import BgeM3Embedder
from docker_agent.rag.evaluation import RetrievalCase, evaluate_case, summarize_metrics
from docker_agent.rag.store import search_similar_chunks

DEFAULT_INPUT = Path("data/eval/retrieval_baseline.jsonl")
K_VALUES = (1, 3, 5)


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
            if not case_id or not query:
                raise ValueError(f"Case at {path}:{line_number} requires id and query")
            if not isinstance(relevant, list) or not relevant:
                raise ValueError(
                    f"Case {case_id} at {path}:{line_number} requires relevant_file_paths"
                )

            cases.append(
                RetrievalCase(
                    case_id=case_id,
                    query=query,
                    relevant_file_paths=frozenset(str(item) for item in relevant),
                )
            )
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate dense Docker Docs retrieval.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--top-k", type=int, default=max(K_VALUES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Evaluation file not found: {args.input}")
    if args.top_k < max(K_VALUES):
        raise SystemExit(f"--top-k must be at least {max(K_VALUES)}")

    cases = load_cases(args.input)
    if not cases:
        raise SystemExit("Evaluation file contains no cases")

    embedder = BgeM3Embedder()
    vectors = embedder.embed_documents(
        [case.query for case in cases],
        show_progress_bar=False,
    )
    engine = create_db_engine()

    case_metrics = []
    for case, vector in zip(cases, vectors, strict=True):
        results = search_similar_chunks(engine, vector, top_k=args.top_k)
        metrics = evaluate_case(case, results, k_values=K_VALUES)
        case_metrics.append(metrics)

        top1 = results[0] if results else None
        top1_label = top1.file_path if top1 is not None else "<no results>"
        rank_label = metrics.first_relevant_rank or "MISS"
        print(
            f"[{case.case_id}] first_relevant={rank_label} "
            f"top1={top1_label} query={case.query}"
        )

    summary = summarize_metrics(case_metrics, k_values=K_VALUES)
    payload = {
        "cases": summary.cases,
        "hit_at": {str(k): round(value, 4) for k, value in summary.hit_at.items()},
        "recall_at": {str(k): round(value, 4) for k, value in summary.recall_at.items()},
        "mrr": round(summary.mrr, 4),
    }
    print("\nSummary")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
