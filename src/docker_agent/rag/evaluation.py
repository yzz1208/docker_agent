from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Any, Protocol


class RetrievalResult(Protocol):
    file_path: str
    section_path: list[str]


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_file_paths: frozenset[str]
    relevant_section_terms: tuple[str, ...] = ()

    @property
    def has_section_labels(self) -> bool:
        return bool(self.relevant_section_terms)


@dataclass(frozen=True, slots=True)
class RetrievalCaseMetrics:
    case_id: str
    first_relevant_rank: int | None
    hit_at: dict[int, bool]
    recall_at: dict[int, float]
    section_first_relevant_rank: int | None
    section_hit_at: dict[int, bool]
    has_section_labels: bool

    @property
    def reciprocal_rank(self) -> float:
        if self.first_relevant_rank is None:
            return 0.0
        return 1.0 / self.first_relevant_rank

    @property
    def section_reciprocal_rank(self) -> float | None:
        if not self.has_section_labels:
            return None
        if self.section_first_relevant_rank is None:
            return 0.0
        return 1.0 / self.section_first_relevant_rank


@dataclass(frozen=True, slots=True)
class RetrievalSummary:
    cases: int
    hit_at: dict[int, float]
    recall_at: dict[int, float]
    mrr: float
    section_cases: int
    section_hit_at: dict[int, float]
    section_mrr: float


def evaluate_case(
    case: RetrievalCase,
    results: Sequence[RetrievalResult],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> RetrievalCaseMetrics:
    """Evaluate one retrieval query at document and optional section level."""

    if not case.relevant_file_paths:
        raise ValueError(f"Case {case.case_id} has no relevant_file_paths")
    if any(k <= 0 for k in k_values):
        raise ValueError("k_values must contain only positive integers")

    ranked_paths = [result.file_path for result in results]
    first_relevant_rank = _first_rank(
        results,
        lambda result: result.file_path in case.relevant_file_paths,
    )

    hit_at: dict[int, bool] = {}
    recall_at: dict[int, float] = {}
    for k in k_values:
        retrieved = set(ranked_paths[:k])
        relevant_found = retrieved & case.relevant_file_paths
        hit_at[k] = bool(relevant_found)
        recall_at[k] = len(relevant_found) / len(case.relevant_file_paths)

    section_first_relevant_rank: int | None = None
    section_hit_at: dict[int, bool] = {}
    if case.has_section_labels:
        section_first_relevant_rank = _first_rank(
            results,
            lambda result: _is_section_relevant(case, result),
        )
        for k in k_values:
            section_hit_at[k] = any(
                _is_section_relevant(case, result) for result in results[:k]
            )

    return RetrievalCaseMetrics(
        case_id=case.case_id,
        first_relevant_rank=first_relevant_rank,
        hit_at=hit_at,
        recall_at=recall_at,
        section_first_relevant_rank=section_first_relevant_rank,
        section_hit_at=section_hit_at,
        has_section_labels=case.has_section_labels,
    )


def summarize_metrics(
    metrics: list[RetrievalCaseMetrics],
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> RetrievalSummary:
    """Aggregate document metrics and the subset with section labels."""

    if not metrics:
        return RetrievalSummary(
            cases=0,
            hit_at={k: 0.0 for k in k_values},
            recall_at={k: 0.0 for k in k_values},
            mrr=0.0,
            section_cases=0,
            section_hit_at={k: 0.0 for k in k_values},
            section_mrr=0.0,
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

    section_metrics = [item for item in metrics if item.has_section_labels]
    if section_metrics:
        section_hit_at = {
            k: mean(1.0 if item.section_hit_at[k] else 0.0 for item in section_metrics)
            for k in k_values
        }
        section_ranks = [
            item.section_reciprocal_rank
            for item in section_metrics
            if item.section_reciprocal_rank is not None
        ]
        section_mrr = mean(section_ranks)
    else:
        section_hit_at = {k: 0.0 for k in k_values}
        section_mrr = 0.0

    return RetrievalSummary(
        cases=len(metrics),
        hit_at=hit_at,
        recall_at=recall_at,
        mrr=mrr,
        section_cases=len(section_metrics),
        section_hit_at=section_hit_at,
        section_mrr=section_mrr,
    )


def validate_case_labels(
    cases: list[RetrievalCase],
    chunk_rows: list[dict[str, Any]],
) -> None:
    """Ensure every evaluation label exists in the currently processed corpus.

    This protects the evaluation from silently becoming invalid when Docker Docs
    paths/headings change or when the selected knowledge scope is modified.
    """

    sections_by_file: dict[str, set[str]] = {}
    for row in chunk_rows:
        file_path = str(row.get("file_path") or "")
        section_path = row.get("section_path")
        if not file_path or not isinstance(section_path, list):
            continue
        joined = " > ".join(str(part) for part in section_path).casefold()
        sections_by_file.setdefault(file_path, set()).add(joined)

    missing_files: list[str] = []
    missing_sections: list[str] = []

    for case in cases:
        for file_path in case.relevant_file_paths:
            if file_path not in sections_by_file:
                missing_files.append(f"{case.case_id}: {file_path}")

        if not case.has_section_labels:
            continue

        candidate_sections = {
            section
            for file_path in case.relevant_file_paths
            for section in sections_by_file.get(file_path, set())
        }
        if not any(
            term.casefold() in section
            for term in case.relevant_section_terms
            for section in candidate_sections
        ):
            terms = ", ".join(case.relevant_section_terms)
            missing_sections.append(f"{case.case_id}: [{terms}]")

    problems: list[str] = []
    if missing_files:
        problems.append("missing files:\n  - " + "\n  - ".join(sorted(missing_files)))
    if missing_sections:
        problems.append("missing section labels:\n  - " + "\n  - ".join(sorted(missing_sections)))

    if problems:
        raise ValueError("Evaluation labels do not match the processed corpus:\n" + "\n".join(problems))


def _first_rank(
    results: Sequence[RetrievalResult],
    predicate: Callable[[RetrievalResult], bool],
) -> int | None:
    for rank, result in enumerate(results, start=1):
        if predicate(result):
            return rank
    return None


def _is_section_relevant(case: RetrievalCase, result: RetrievalResult) -> bool:
    if result.file_path not in case.relevant_file_paths:
        return False
    joined = " > ".join(result.section_path).casefold()
    return any(term.casefold() in joined for term in case.relevant_section_terms)
