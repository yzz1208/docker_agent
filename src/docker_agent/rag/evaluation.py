from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from docker_agent.rag.store import SearchResult


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_file_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class RetrievalCaseMetrics:
    case_id: str
    first_relevant_rank: int | None
    hit_at: dict[int, bool]
    recall_at: dict[int, float]

    @property
    def reciprocal_rank(self) -> float:
        if self.first_relevant_rank is None:
            return 0.0
        return 1.0 / self.first_relevant_rank


@dataclass(frozen=True, slots=True)
class RetrievalSummary:
    cases: int
    hit_at: dict[int, float]
    recall_at: dict[int, float]
    mrr: float


def evaluate_case(
    case: RetrievalCase,
    results: list[SearchResult],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> RetrievalCaseMetrics:
    """Evaluate one retrieval query against stable source file labels."""

    if not case.relevant_file_paths:
        raise ValueError(f"Case {case.case_id} has no relevant_file_paths")
    if any(k <= 0 for k in k_values):
        raise ValueError("k_values must contain only positive integers")

    ranked_paths = [result.file_path for result in results]
    first_relevant_rank: int | None = None
    for rank, file_path in enumerate(ranked_paths, start=1):
        if file_path in case.relevant_file_paths:
            first_relevant_rank = rank
            break

    hit_at: dict[int, bool] = {}
    recall_at: dict[int, float] = {}
    for k in k_values:
        retrieved = set(ranked_paths[:k])
        relevant_found = retrieved & case.relevant_file_paths
        hit_at[k] = bool(relevant_found)
        recall_at[k] = len(relevant_found) / len(case.relevant_file_paths)

    return RetrievalCaseMetrics(
        case_id=case.case_id,
        first_relevant_rank=first_relevant_rank,
        hit_at=hit_at,
        recall_at=recall_at,
    )


def summarize_metrics(
    metrics: list[RetrievalCaseMetrics],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> RetrievalSummary:
    """Aggregate retrieval metrics across the evaluation set."""

    if not metrics:
        return RetrievalSummary(
            cases=0,
            hit_at={k: 0.0 for k in k_values},
            recall_at={k: 0.0 for k in k_values},
            mrr=0.0,
        )

    hit_at = {
        k: mean(1.0 if item.hit_at[k] else 0.0 for item in metrics)
        for k in k_values
    }
    recall_at = {
        k: mean(item.recall_at[k] for item in metrics)
        for k in k_values
    }
    mrr = mean(item.reciprocal_rank for item in metrics)

    return RetrievalSummary(
        cases=len(metrics),
        hit_at=hit_at,
        recall_at=recall_at,
        mrr=mrr,
    )
