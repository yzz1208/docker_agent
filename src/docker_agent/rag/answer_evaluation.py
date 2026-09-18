from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from typing import Any

from docker_agent.rag.answer import GroundedAnswer
from docker_agent.rag.context import RagContext
from docker_agent.rag.llm import ChatModel


@dataclass(frozen=True, slots=True)
class AnswerEvalCase:
    case_id: str
    question: str
    answerable: bool
    expected_file_paths: frozenset[str] = frozenset()
    required_concept_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class DeterministicAnswerMetrics:
    case_id: str
    citations_present: bool
    cited_source_count: int
    retrieved_expected_source_hit: bool | None
    cited_expected_source_hit: bool | None
    expected_source_recall: float | None
    concept_coverage: float


@dataclass(frozen=True, slots=True)
class AnswerJudgeResult:
    groundedness: int
    citation_correctness: int
    completeness: int
    insufficient_evidence_handling: str
    unsupported_claims: tuple[str, ...]
    rationale: str


def evaluate_answer_deterministically(
    case: AnswerEvalCase,
    result: GroundedAnswer,
) -> DeterministicAnswerMetrics:
    """Compute stable non-LLM answer metrics for one evaluation case."""

    retrieved_paths = {source.file_path for source in result.sources}
    cited_paths = {source.file_path for source in result.cited_sources}

    if case.expected_file_paths:
        retrieved_hit: bool | None = bool(retrieved_paths & case.expected_file_paths)
        cited_hit: bool | None = bool(cited_paths & case.expected_file_paths)
        source_recall: float | None = (
            len(retrieved_paths & case.expected_file_paths) / len(case.expected_file_paths)
        )
    else:
        retrieved_hit = None
        cited_hit = None
        source_recall = None

    answer_folded = result.answer.casefold()
    matched_groups = 0
    for alternatives in case.required_concept_groups:
        if any(term.casefold() in answer_folded for term in alternatives):
            matched_groups += 1

    if case.required_concept_groups:
        concept_coverage = matched_groups / len(case.required_concept_groups)
    else:
        concept_coverage = 1.0

    return DeterministicAnswerMetrics(
        case_id=case.case_id,
        citations_present=bool(result.citation_indices),
        cited_source_count=len(result.cited_sources),
        retrieved_expected_source_hit=retrieved_hit,
        cited_expected_source_hit=cited_hit,
        expected_source_recall=source_recall,
        concept_coverage=concept_coverage,
    )


def build_judge_prompt(
    case: AnswerEvalCase,
    result: GroundedAnswer,
    context: RagContext,
) -> str:
    """Build a constrained rubric prompt for optional LLM-assisted evaluation."""

    expected_paths = ", ".join(sorted(case.expected_file_paths)) or "<none>"
    concept_groups = [" OR ".join(group) for group in case.required_concept_groups]
    concepts = "; ".join(concept_groups) or "<none>"

    return (
        "Evaluate a Docker support answer against the retrieved evidence.\n"
        "Do not use outside Docker knowledge. Judge only what the supplied evidence supports.\n\n"
        f"Case ID: {case.case_id}\n"
        f"Question: {case.question}\n"
        f"Expected answerable from documentation: {str(case.answerable).lower()}\n"
        f"Reference file labels for this eval case: {expected_paths}\n"
        f"Expected concepts for completeness: {concepts}\n\n"
        "Retrieved evidence:\n"
        f"{context.text}\n\n"
        "Generated answer:\n"
        f"{result.answer}\n\n"
        "Return JSON only with exactly these fields:\n"
        "{\n"
        '  "groundedness": 1-5,\n'
        '  "citation_correctness": 1-5,\n'
        '  "completeness": 1-5,\n'
        '  "insufficient_evidence_handling": "pass" | "fail" | "not_applicable",\n'
        '  "unsupported_claims": ["brief claim", ...],\n'
        '  "rationale": "brief explanation"\n'
        "}\n\n"
        "Rubric:\n"
        "- groundedness: 5 means every material factual claim is supported by the evidence; "
        "1 means major unsupported claims.\n"
        "- citation_correctness: 5 means citations directly support the nearby claims; "
        "1 means citations are mostly mismatched.\n"
        "- completeness: 5 means the answer covers the important evidence-backed parts of "
        "the question without unnecessary omissions; 1 means it misses the core answer.\n"
        "- insufficient_evidence_handling: use not_applicable for answerable=true. For "
        "answerable=false, pass only if the answer clearly says the runtime-specific fact "
        "cannot be determined from the supplied documentation and does not fabricate it."
    )


def judge_answer(
    case: AnswerEvalCase,
    result: GroundedAnswer,
    context: RagContext,
    judge_model: ChatModel,
) -> AnswerJudgeResult:
    """Run an optional LLM-as-judge pass and validate its JSON response."""

    raw = judge_model.complete(
        system_prompt=(
            "You are a strict RAG evaluator. Return only valid JSON and evaluate only "
            "against the supplied evidence."
        ),
        user_prompt=build_judge_prompt(case, result, context),
    )
    payload = _parse_json_object(raw)

    groundedness = _score(payload, "groundedness")
    citation_correctness = _score(payload, "citation_correctness")
    completeness = _score(payload, "completeness")

    handling = str(payload.get("insufficient_evidence_handling") or "").strip()
    allowed_handling = {"pass", "fail", "not_applicable"}
    if handling not in allowed_handling:
        raise ValueError(
            "Judge field insufficient_evidence_handling must be pass, fail, or not_applicable"
        )

    unsupported = payload.get("unsupported_claims", [])
    if not isinstance(unsupported, list):
        raise TypeError("Judge field unsupported_claims must be a list")

    rationale = str(payload.get("rationale") or "").strip()
    return AnswerJudgeResult(
        groundedness=groundedness,
        citation_correctness=citation_correctness,
        completeness=completeness,
        insufficient_evidence_handling=handling,
        unsupported_claims=tuple(str(item) for item in unsupported if str(item).strip()),
        rationale=rationale,
    )


def summarize_deterministic_metrics(
    metrics: list[DeterministicAnswerMetrics],
) -> dict[str, float | int]:
    if not metrics:
        return {
            "cases": 0,
            "citation_presence_rate": 0.0,
            "mean_cited_sources": 0.0,
            "retrieved_expected_source_hit_rate": 0.0,
            "cited_expected_source_hit_rate": 0.0,
            "mean_expected_source_recall": 0.0,
            "mean_concept_coverage": 0.0,
        }

    with_expected = [
        item for item in metrics if item.retrieved_expected_source_hit is not None
    ]
    return {
        "cases": len(metrics),
        "citation_presence_rate": mean(
            1.0 if item.citations_present else 0.0 for item in metrics
        ),
        "mean_cited_sources": mean(item.cited_source_count for item in metrics),
        "retrieved_expected_source_hit_rate": _mean_optional_bool(
            [item.retrieved_expected_source_hit for item in with_expected]
        ),
        "cited_expected_source_hit_rate": _mean_optional_bool(
            [item.cited_expected_source_hit for item in with_expected]
        ),
        "mean_expected_source_recall": (
            mean(item.expected_source_recall or 0.0 for item in with_expected)
            if with_expected
            else 0.0
        ),
        "mean_concept_coverage": mean(item.concept_coverage for item in metrics),
    }


def summarize_judge_results(results: list[AnswerJudgeResult]) -> dict[str, float | int]:
    if not results:
        return {
            "cases": 0,
            "mean_groundedness": 0.0,
            "mean_citation_correctness": 0.0,
            "mean_completeness": 0.0,
            "insufficient_evidence_pass_rate": 0.0,
        }

    insufficient = [
        item
        for item in results
        if item.insufficient_evidence_handling != "not_applicable"
    ]
    return {
        "cases": len(results),
        "mean_groundedness": mean(item.groundedness for item in results),
        "mean_citation_correctness": mean(
            item.citation_correctness for item in results
        ),
        "mean_completeness": mean(item.completeness for item in results),
        "insufficient_evidence_pass_rate": (
            mean(
                1.0 if item.insufficient_evidence_handling == "pass" else 0.0
                for item in insufficient
            )
            if insufficient
            else 0.0
        ),
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("Judge response must be a JSON object")
    return payload


def _score(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise ValueError(f"Judge field {field} must be an integer from 1 to 5")
    return value


def _mean_optional_bool(values: list[bool | None]) -> float:
    clean = [value for value in values if value is not None]
    if not clean:
        return 0.0
    return mean(1.0 if value else 0.0 for value in clean)
